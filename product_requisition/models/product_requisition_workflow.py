import logging
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class ProductRequisitionWorkflow(models.Model):
    """
    Configurable approval workflow template for product requisitions.
    One active workflow per department (or one global fallback).
    """
    _name = 'product.requisition.workflow'
    _description = 'Product Requisition Workflow'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'department_id, sequence'
    _rec_name = 'name'

    name = fields.Char(string='Workflow Name', required=True, tracking=True)
    department_id = fields.Many2one(
        'hr.department', string='Department', tracking=True,
        help="Leave empty to create a global fallback workflow used when "
             "no department-specific workflow exists.",
    )
    active = fields.Boolean(default=True, tracking=True)
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company,
        required=True,
    )
    description = fields.Text(string='Description')

    # Steps
    step_ids = fields.One2many(
        'product.requisition.workflow.step', 'workflow_id',
        string='Approval Steps',
    )
    step_count = fields.Integer(compute='_compute_step_count', string='# Steps')
    approver_summary = fields.Char(
        compute='_compute_approver_summary', string='Approval Chain',
    )

    # ── Computed ─────────────────────────────────────────────────────────────

    @api.depends('step_ids')
    def _compute_step_count(self):
        for wf in self:
            wf.step_count = len(wf.step_ids)

    @api.depends('step_ids.approver_id', 'step_ids.name', 'step_ids.sequence')
    def _compute_approver_summary(self):
        for wf in self:
            steps = wf.step_ids.sorted('sequence')
            if steps:
                wf.approver_summary = ' → '.join(
                    f"{s.name} ({s.approver_id.name})" for s in steps
                )
            else:
                wf.approver_summary = 'No steps configured'

    # ── Constraints ──────────────────────────────────────────────────────────

    @api.constrains('department_id', 'active', 'company_id')
    def _check_unique_active_workflow(self):
        """Only one active workflow per department per company."""
        for wf in self:
            if not wf.active:
                continue
            domain = [
                ('id', '!=', wf.id),
                ('active', '=', True),
                ('company_id', '=', wf.company_id.id),
                ('department_id', '=', wf.department_id.id if wf.department_id else False),
            ]
            if self.search(domain, limit=1):
                dept_name = wf.department_id.name if wf.department_id else 'Global (No Department)'
                raise ValidationError(_(
                    "An active workflow already exists for '%s'. "
                    "Please deactivate or delete the existing one first."
                ) % dept_name)

    @api.constrains('step_ids')
    def _check_steps(self):
        for wf in self:
            if wf.active and not wf.step_ids:
                raise ValidationError(
                    _("Active workflow '%s' must have at least one approval step.") % wf.name
                )
            sequences = wf.step_ids.mapped('sequence')
            if len(sequences) != len(set(sequences)):
                raise ValidationError(
                    _("Each step must have a unique sequence number in workflow '%s'.") % wf.name
                )

    # ── Helper ───────────────────────────────────────────────────────────────

    def get_ordered_steps(self):
        """Return steps sorted by sequence as a recordset."""
        self.ensure_one()
        return self.step_ids.sorted('sequence')

    def name_get(self):
        result = []
        for wf in self:
            dept = wf.department_id.name if wf.department_id else 'Global'
            label = f"{wf.name} [{dept}]"
            if not wf.active:
                label += " (Inactive)"
            result.append((wf.id, label))
        return result


class ProductRequisitionWorkflowStep(models.Model):
    """
    A single configurable step in a product requisition approval workflow.
    Steps are ordered by sequence and executed one by one.
    """
    _name = 'product.requisition.workflow.step'
    _description = 'Product Requisition Workflow Step'
    _order = 'workflow_id, sequence'

    workflow_id = fields.Many2one(
        'product.requisition.workflow', string='Workflow',
        required=True, ondelete='cascade',
    )
    sequence = fields.Integer(string='Step #', required=True, default=10)
    name = fields.Char(
        string='Role / Step Name', required=True,
        help="Descriptive label for this approval level, "
             "e.g. Line Manager, Finance, Head of Finance, CEO.",
    )
    approver_id = fields.Many2one(
        'res.users', string='Approver', required=True,
        help="User who will approve or reject at this step.",
    )
    is_required = fields.Boolean(
        string='Required', default=True,
        help="Uncheck to allow this step to be skipped if the approver is unavailable.",
    )
    timeout_days = fields.Integer(
        string='Timeout (days)', default=3,
        help="Number of days before this approval is considered overdue.",
    )
    notes = fields.Text(
        string='Instructions',
        help="Optional instructions shown to the approver when their activity is created.",
    )

    @api.constrains('timeout_days')
    def _check_timeout(self):
        for step in self:
            if step.timeout_days < 1:
                raise ValidationError(_("Timeout must be at least 1 day."))
