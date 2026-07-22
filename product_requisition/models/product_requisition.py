import logging
from datetime import timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ProductRequisition(models.Model):
    _name = "product.requisition"
    _description = "Product Requisition"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "write_date desc"

    # ── Basic Fields ─────────────────────────────────────────────────────────

    name = fields.Char(
        string="Reference",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _("New"),
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Requested By (Contact)",
        required=True,
        tracking=True,
        default=lambda self: self.env.user.partner_id,
    )
    user_id = fields.Many2one(
        "res.users",
        string="Requester",
        required=True,
        tracking=True,
        readonly=True,
        default=lambda self: self.env.user,
    )
    submission_source = fields.Selection(
        [('portal', 'Portal')],
        string='Source',
        compute='_compute_submission_source',
        store=False,
    )
    department_id = fields.Many2one(
        'hr.department',
        string='Department',
        tracking=True,
        default=lambda self: self._default_department(),
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
    )
    date_request = fields.Date(
        string="Request Date",
        required=True,
        default=fields.Date.today,
        tracking=True,
    )
    date_required = fields.Date(
        string="Required By",
        tracking=True,
    )
    notes = fields.Text(string="Notes / Justification")
    file_no = fields.Char(
        string='File No.',
        tracking=True,
        copy=False,
        help='Internal file / diary reference number for this indent.',
    )
    priority = fields.Selection(
        [('0', 'Normal'), ('1', 'Urgent'), ('2', 'Very Urgent')],
        string='Priority',
        default='0',
        tracking=True,
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        compute='_compute_employee_id',
        store=True,
        help='Employee record linked to the requester user.',
    )

    # ── Indent Classification ─────────────────────────────────────────────────

    purchase_type = fields.Selection(
        [('goods', 'Goods'), ('service', 'Service')],
        string='Type',
        default='goods',
        required=True,
        tracking=True,
    )
    purchase_mode = fields.Selection(
        [('local', 'Local'), ('foreign', 'Foreign')],
        string='Purchase Mode',
        default='local',
        required=True,
        tracking=True,
        help='Local: domestic purchase in company currency.\n'
             'Foreign: international purchase — affects currency and incoterm on the RFQ.',
    )
    purchase_option = fields.Selection(
        [
            ('single',             'Single Source'),
            ('swift',              'Swift'),
            ('limited',            'Limited Tender'),
            ('purchase_committee', 'Purchase Committee'),
        ],
        string='Purchase Option',
        default='single',
        tracking=True,
    )
    estimated_cost = fields.Float(
        string='Estimated Cost',
        digits='Product Price',
        tracking=True,
        help='Total budget estimate for this indent.',
    )
    analytic_account_id = fields.Many2one(
        'account.analytic.account',
        string='Account Head / Project',
        tracking=True,
        help='Analytic account or project this requisition is charged to.',
    )
    delivery_lead_days = fields.Integer(
        string='Delivery Lead Time',
        default=30,
        help='Expected delivery duration from order date.',
    )
    delivery_lead_unit = fields.Selection(
        [('days', 'Days'), ('weeks', 'Weeks'), ('months', 'Months')],
        string='Lead Time Unit',
        default='days',
    )

    # ── State ────────────────────────────────────────────────────────────────

    state = fields.Selection(
        [
            ('draft',       'Draft'),
            ('submitted',   'Submitted'),      # set by portal on creation
            ('in_approval', 'In Approval'),    # workflow is running
            ('approved',    'Approved'),
            ('rejected',    'Rejected'),
            ('cancelled',   'Cancelled'),
            ('rfq_created', 'RFQ Created'),
            ('done',        'Done'),
        ],
        string="Status",
        default="draft",
        tracking=True,
        copy=False,
    )

    # ── Product Lines ────────────────────────────────────────────────────────

    requisition_line_ids = fields.One2many(
        "product.requisition.line",
        "requisition_id",
        string="Requisition Lines",
    )
    line_count = fields.Integer(
        string="# Products",
        compute="_compute_line_count",
        store=True,
    )

    # ── Workflow ─────────────────────────────────────────────────────────────

    workflow_id = fields.Many2one(
        'product.requisition.workflow',
        string='Approval Workflow',
        compute='_compute_workflow',
        store=True,
        help="Resolved automatically from the department; "
             "falls back to the global workflow when none is set for the department.",
    )
    # 0-based index into the ordered step list; 0 = first step pending
    current_step_index = fields.Integer(
        string='Current Step Index',
        default=0,
        copy=False,
    )
    current_step_name = fields.Char(
        string='Current Step',
        compute='_compute_current_approver',
        store=True,
    )
    current_approver_id = fields.Many2one(
        'res.users',
        string='Current Approver',
        compute='_compute_current_approver',
        store=True,
    )
    next_approver_id = fields.Many2one(
        'res.users',
        string='Next Approver',
        compute='_compute_current_approver',
        store=True,
    )
    rejection_reason = fields.Text(string='Rejection Reason', tracking=True)
    approval_history_ids = fields.One2many(
        'product.requisition.approval.history',
        'requisition_id',
        string='Approval History',
    )
    approval_progress = fields.Html(
        string='Approval Progress',
        compute='_compute_approval_progress',
        sanitize=False,
    )

    # ── RFQ ──────────────────────────────────────────────────────────────────

    rfq_count = fields.Integer(
        string='RFQ Count',
        compute='_compute_rfq_count',
    )

    # ── Button Visibility (computed, not stored) ──────────────────────────────

    can_submit    = fields.Boolean(compute='_compute_button_visibility')
    can_approve   = fields.Boolean(compute='_compute_button_visibility')
    can_reject    = fields.Boolean(compute='_compute_button_visibility')
    can_reset     = fields.Boolean(compute='_compute_button_visibility')
    can_cancel    = fields.Boolean(compute='_compute_button_visibility')
    can_create_rfq = fields.Boolean(compute='_compute_button_visibility')
    can_mark_done = fields.Boolean(compute='_compute_button_visibility')

    # ── Defaults ─────────────────────────────────────────────────────────────

    def _default_department(self):
        try:
            emp = self.env['hr.employee'].sudo().search(
                [('user_id', '=', self.env.user.id)], limit=1
            )
            if emp and emp.department_id:
                return emp.department_id.id
        except Exception:
            pass
        return False

    # ── Computed ─────────────────────────────────────────────────────────────

    @api.depends('user_id')
    def _compute_employee_id(self):
        for rec in self:
            emp = self.env['hr.employee'].sudo().search(
                [('user_id', '=', rec.user_id.id)], limit=1
            )
            rec.employee_id = emp or False

    @api.depends("requisition_line_ids")
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.requisition_line_ids)

    @api.depends('department_id', 'company_id')
    def _compute_workflow(self):
        """
        Resolve the active workflow to use for this requisition:
        1. Department-specific active workflow
        2. Global (no-department) active workflow
        """
        for record in self:
            company = record.company_id or self.env.company
            workflow = False
            if record.department_id:
                workflow = self.env['product.requisition.workflow'].search([
                    ('department_id', '=', record.department_id.id),
                    ('active', '=', True),
                    ('company_id', '=', company.id),
                ], order='sequence', limit=1)
            if not workflow:
                workflow = self.env['product.requisition.workflow'].search([
                    ('department_id', '=', False),
                    ('active', '=', True),
                    ('company_id', '=', company.id),
                ], order='sequence', limit=1)
            record.workflow_id = workflow

    @api.depends('state', 'workflow_id', 'current_step_index')
    def _compute_current_approver(self):
        for record in self:
            if record.state == 'in_approval' and record.workflow_id:
                steps = record.workflow_id.get_ordered_steps()
                idx = record.current_step_index
                if steps and idx < len(steps):
                    step = steps[idx]
                    record.current_step_name  = step.name
                    record.current_approver_id = step.approver_id
                    nxt = idx + 1
                    record.next_approver_id = steps[nxt].approver_id if nxt < len(steps) else False
                else:
                    record.current_step_name   = False
                    record.current_approver_id = False
                    record.next_approver_id    = False
            else:
                record.current_step_name   = False
                record.current_approver_id = False
                record.next_approver_id    = False

    @api.depends('workflow_id', 'workflow_id.step_ids',
                 'current_step_index', 'state', 'approval_history_ids')
    def _compute_approval_progress(self):
        for record in self:
            if not record.workflow_id or not record.workflow_id.step_ids:
                record.approval_progress = (
                    '<p class="text-muted fst-italic">'
                    'No workflow configured for this requisition.</p>'
                )
                continue
            steps = record.workflow_id.get_ordered_steps()
            parts = []
            for i, step in enumerate(steps):
                if record.state in ('approved', 'rfq_created', 'done') or (
                    record.state in ('in_approval',) and i < record.current_step_index
                ):
                    badge = '<span class="badge rounded-pill bg-success me-1">&#10003;</span>'
                    cls   = 'text-success'
                elif record.state == 'in_approval' and i == record.current_step_index:
                    badge = '<span class="badge rounded-pill bg-warning text-dark me-1">&#9203;</span>'
                    cls   = 'fw-bold'
                else:
                    badge = '<span class="badge rounded-pill bg-secondary me-1">&#9675;</span>'
                    cls   = 'text-muted'
                parts.append(
                    f'<span class="{cls}">'
                    f'{badge}{step.name}: <em>{step.approver_id.name}</em>'
                    f'</span>'
                )
            separator = ' <span class="text-muted mx-1">&#8594;</span> '
            record.approval_progress = separator.join(parts)

    @api.depends(
        'state', 'user_id', 'workflow_id',
        'current_step_index', 'current_approver_id',
    )
    def _compute_button_visibility(self):
        for record in self:
            user      = self.env.user
            is_admin  = user.has_group('product_requisition.group_pr_admin')
            is_req    = (user == record.user_id)

            record.can_submit = (
                record.state in ('draft', 'submitted') and
                (is_req or is_admin)
            )
            record.can_approve = (
                record.state == 'in_approval' and
                record._can_user_approve()
            )
            record.can_reject = record.can_approve
            record.can_reset = (
                record.state in ('rejected', 'cancelled') and
                (is_req or is_admin)
            )
            record.can_cancel = (
                record.state not in ('approved', 'rfq_created', 'done', 'cancelled') and
                (is_req or is_admin)
            )
            record.can_create_rfq = (
                record.state in ('approved', 'rfq_created') and
                (
                    user.has_group('purchase.group_purchase_user') or
                    is_admin
                )
            )
            record.can_mark_done = (
                record.state == 'rfq_created' and
                (user.has_group('purchase.group_purchase_manager') or is_admin)
            )

    def _compute_rfq_count(self):
        for record in self:
            if record.name and record.name != _('New'):
                record.rfq_count = self.env['purchase.order'].search_count(
                    [('origin', '=', record.name)]
                )
            else:
                record.rfq_count = 0

    @api.depends('user_id')
    def _compute_submission_source(self):
        for rec in self:
            # user_id.share is True for portal and public users
            rec.submission_source = 'portal' if rec.user_id.share else False

    # ── ORM ──────────────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("product.requisition")
                    or _("New")
                )
            # Auto-populate department when not provided
            if not vals.get('department_id'):
                uid = vals.get('user_id', self.env.user.id)
                emp = self.env['hr.employee'].sudo().search(
                    [('user_id', '=', uid)], limit=1
                )
                if emp and emp.department_id:
                    vals['department_id'] = emp.department_id.id
             # ── Block creation if no workflow is configured ──────────────────
            company_id = vals.get('company_id') or self.env.company.id
            dept_id = vals.get('department_id')
            workflow = False
            if dept_id:
                workflow = self.env['product.requisition.workflow'].search([
                    ('department_id', '=', dept_id),
                    ('active', '=', True),
                    ('company_id', '=', company_id),
                ], limit=1)
            if not workflow:
                workflow = self.env['product.requisition.workflow'].search([
                    ('department_id', '=', False),
                    ('active', '=', True),
                    ('company_id', '=', company_id),
                ], limit=1)
            if not workflow:
                dept = self.env['hr.department'].browse(dept_id) if dept_id else None
                raise UserError(_(
                    "Cannot create requisition: no approval workflow is configured "
                    "for department '%s'.\n\n"
                    "Please ask your administrator to set up a workflow under:\n"
                    "Product Requisitions → Configuration → Approval Workflows."
                ) % (dept.name if dept else _('Unknown')))           

        records = super().create(vals_list)
        for rec in records:
            if rec.user_id:
                rec.message_subscribe(partner_ids=[rec.user_id.partner_id.id])
        return records

    @api.onchange('user_id')
    def _onchange_user_id(self):
        if not self.user_id:
            return
        try:
            emp = self.env['hr.employee'].sudo().search(
                [('user_id', '=', self.user_id.id)], limit=1
            )
            if emp and emp.department_id:
                self.department_id = emp.department_id
        except Exception:
            pass

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _can_user_approve(self):
        """Return True if the current user may approve/reject at the current step."""
        if self.state != 'in_approval' or not self.workflow_id:
            return False
        steps = self.workflow_id.get_ordered_steps()
        if not steps or self.current_step_index >= len(steps):
            return False
        return (
            self.env.user == steps[self.current_step_index].approver_id or
            self.env.user.has_group('product_requisition.group_pr_admin')
        )

    def _log_history(self, step_name, decision, comments=''):
        """Create an approval history record for `self`."""
        self.env['product.requisition.approval.history'].create({
            'requisition_id': self.id,
            'user_id':        self.env.user.id,
            'step_name':      step_name,
            'decision':       decision,
            'comments':       comments,
        })

    def _schedule_approval_activity(self, approver, step):
        """Schedule a To-do activity for an approver."""
        try:
            self.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=approver.id,
                summary=_('Requisition Approval Required: %s') % self.name,
                note=_(
                    'A product requisition requires your approval at step: <b>%s</b>.<br/>'
                    '<br/>'
                    'Reference: <b>%s</b><br/>'
                    'Requester: %s<br/>'
                    'Department: %s<br/>'
                    '%s'
                    '<br/>Please open the record to Approve or Reject.'
                ) % (
                    step.name,
                    self.name,
                    self.user_id.name,
                    self.department_id.name if self.department_id else 'N/A',
                    ('<br/>Instructions: ' + step.notes) if step.notes else '',
                ),
                date_deadline=fields.Date.today() + timedelta(days=step.timeout_days or 3),
            )
        except Exception as e:
            _logger.warning("Could not schedule activity for %s: %s", approver.name, e)

    # ── Actions ──────────────────────────────────────────────────────────────

    def action_submit(self):
        """
        Start the approval workflow.
        Works on both 'draft' (internal) and 'submitted' (portal-created) records.
        """
        for rec in self:
            if not rec.requisition_line_ids:
                raise UserError(
                    _("Please add at least one product line before submitting.")
                )
            if not rec.workflow_id:
                raise UserError(_(
                    "No approval workflow is configured for department '%s'.\n\n"
                    "Go to  Product Requisitions → Configuration → Approval Workflows "
                    "and create a workflow for this department (or a global one)."
                ) % (rec.department_id.name if rec.department_id else _('Unknown')))

            steps = rec.workflow_id.get_ordered_steps()
            if not steps:
                raise UserError(
                    _("Workflow '%s' has no steps configured. "
                      "Please add at least one approval step.")
                    % rec.workflow_id.name
                )

            rec._log_history('Submission', 'submitted',
                             _('Submitted by %s') % self.env.user.name)
            rec.activity_ids.action_done()
            rec.write({'state': 'in_approval', 'current_step_index': 0})
            rec._schedule_approval_activity(steps[0].approver_id, steps[0])
        return True

    def action_approve(self):
        """Approve the current step and advance the workflow."""
        self.ensure_one()
        if not self._can_user_approve():
            raise UserError(
                _("You are not authorised to approve this requisition at the current step.")
            )

        steps = self.workflow_id.get_ordered_steps()
        current_step = steps[self.current_step_index]

        self._log_history(
            current_step.name, 'approved',
            _('Approved by %s') % self.env.user.name,
        )
        self.message_subscribe(partner_ids=[self.env.user.partner_id.id])

        next_index = self.current_step_index + 1

        if next_index >= len(steps):
            # ── All steps passed → fully approved ──────────────────────────
            self.write({'state': 'approved'})
            self.activity_ids.action_done()
            try:
                self.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=self.user_id.id,
                    summary=_('Requisition Fully Approved: %s') % self.name,
                    note=_(
                        'Your product requisition <b>%s</b> has been fully approved.<br/>'
                        'The procurement team will now create the RFQ.'
                    ) % self.name,
                    date_deadline=fields.Date.today() + timedelta(days=1),
                )
            except Exception as e:
                _logger.warning("Could not notify requester on approval: %s", e)
        else:
            # ── Advance to next step ────────────────────────────────────────
            next_step = steps[next_index]
            self.write({'current_step_index': next_index})
            # Force recompute so the form immediately shows the updated approver
            self._compute_current_approver()
            self.activity_ids.action_done()
            self._schedule_approval_activity(next_step.approver_id, next_step)

        return True

    def action_reject(self):
        """Open the rejection wizard."""
        self.ensure_one()
        if not self._can_user_approve():
            raise UserError(
                _("You are not authorised to reject this requisition at the current step.")
            )
        return {
            'name':      _('Reject Requisition'),
            'type':      'ir.actions.act_window',
            'res_model': 'product.requisition.reject.wizard',
            'view_mode': 'form',
            'target':    'new',
            'context':   {'default_requisition_id': self.id},
        }

    def _do_reject(self, reason):
        """Called by the reject wizard to finalise rejection."""
        self.ensure_one()
        steps     = self.workflow_id.get_ordered_steps() if self.workflow_id else []
        step_name = (
            steps[self.current_step_index].name
            if (steps and self.current_step_index < len(steps))
            else _('N/A')
        )
        self._log_history(step_name, 'rejected', reason)
        self.message_subscribe(partner_ids=[self.env.user.partner_id.id])
        self.write({'state': 'rejected', 'rejection_reason': reason})
        self.activity_ids.action_done()
        try:
            self.activity_schedule(
                'mail.mail_activity_data_warning',
                user_id=self.user_id.id,
                summary=_('Requisition Rejected: %s') % self.name,
                note=_(
                    'Your product requisition <b>%s</b> has been rejected.<br/>'
                    '<br/>'
                    'Rejected by: %s<br/>'
                    'At step: %s<br/>'
                    'Reason: %s<br/>'
                    '<br/>Please review the feedback and resubmit with necessary changes.'
                ) % (self.name, self.env.user.name, step_name, reason),
                date_deadline=fields.Date.today() + timedelta(days=7),
            )
        except Exception as e:
            _logger.warning("Could not notify requester on rejection: %s", e)

    def action_reset_draft(self):
        """Reset a rejected/cancelled requisition back to draft."""
        for rec in self:
            if not (self.env.user == rec.user_id or
                    self.env.user.has_group('product_requisition.group_pr_admin')):
                raise UserError(
                    _("Only the requester or system administrators can reset to draft.")
                )
        self.env['product.requisition.approval.history'].create([{
            'requisition_id': rec.id,
            'user_id':        self.env.user.id,
            'step_name':      _('Reset'),
            'decision':       'reset',
            'comments':       _('Reset to draft by %s') % self.env.user.name,
        } for rec in self])
        self.activity_ids.action_done()
        return self.write({
            'state':               'draft',
            'rejection_reason':    False,
            'current_step_index':  0,
        })

    def action_cancel(self):
        """Cancel the requisition."""
        for rec in self:
            if not (self.env.user == rec.user_id or
                    self.env.user.has_group('product_requisition.group_pr_admin')):
                raise UserError(
                    _("Only the requester or system administrators can cancel.")
                )
        self.env['product.requisition.approval.history'].create([{
            'requisition_id': rec.id,
            'user_id':        self.env.user.id,
            'step_name':      _('Cancellation'),
            'decision':       'cancelled',
            'comments':       _('Cancelled by %s') % self.env.user.name,
        } for rec in self])
        self.activity_ids.action_done()
        return self.write({'state': 'cancelled'})

    def action_create_rfq(self):
        """
        Open the RFQ wizard so the user can select vendor(s), currency,
        incoterm (Foreign), and payment terms before creating the RFQ(s).
        Multiple vendors can be selected to create one RFQ per vendor for
        CST comparison via Odoo's native purchase comparison feature.
        """
        self.ensure_one()
        if self.state not in ('approved', 'rfq_created'):
            raise UserError(
                _("Only approved requisitions can have an RFQ created.")
            )
        if not self.requisition_line_ids:
            raise UserError(_("No product lines found on this requisition."))

        # Pre-select currency based on purchase mode
        if self.purchase_mode == 'foreign':
            currency = self.env.ref('base.USD', raise_if_not_found=False)
            if not currency:
                currency = self.env.company.currency_id
        else:
            currency = self.env.company.currency_id

        return {
            'name':      _('Create Request for Quotation'),
            'type':      'ir.actions.act_window',
            'res_model': 'product.requisition.rfq.wizard',
            'view_mode': 'form',
            'target':    'new',
            'context': {
                'default_requisition_id': self.id,
                'default_currency_id':    currency.id,
            },
        }

    def action_view_rfqs(self):
        """Open the list of purchase orders (RFQs/POs) linked to this requisition."""
        self.ensure_one()
        return {
            'type':      'ir.actions.act_window',
            'name':      _('RFQs / Purchase Orders – %s') % self.name,
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain':    [('origin', '=', self.name)],
            'target':    'current',
        }

    def action_mark_done(self):
        """Mark as done once the procurement process is complete."""
        self.write({'state': 'done'})

    def action_print_requisition(self):
        """Print the Product Requisition / Indent form as a PDF."""
        return self.env.ref(
            'product_requisition.action_report_product_requisition'
        ).report_action(self)
