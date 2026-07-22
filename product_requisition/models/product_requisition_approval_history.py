from odoo import models, fields, api, _


class ProductRequisitionApprovalHistory(models.Model):
    """
    Immutable audit trail of every decision made on a product requisition.
    Records are created by the system; never edited or deleted by users.
    """
    _name = 'product.requisition.approval.history'
    _description = 'Product Requisition Approval History'
    _order = 'date asc, id asc'

    requisition_id = fields.Many2one(
        'product.requisition', string='Requisition',
        required=True, ondelete='cascade', index=True,
    )
    user_id = fields.Many2one(
        'res.users', string='User',
        required=True, default=lambda self: self.env.user,
    )
    step_name = fields.Char(string='Step / Role')
    decision = fields.Selection([
        ('submitted', 'Submitted'),
        ('approved',  'Approved'),
        ('rejected',  'Rejected'),
        ('reset',     'Reset to Draft'),
        ('cancelled', 'Cancelled'),
    ], string='Decision', required=True)
    comments = fields.Text(string='Comments / Reason')
    date = fields.Datetime(
        string='Date', default=fields.Datetime.now, required=True,
    )
    is_rejection = fields.Boolean(
        string='Is Rejection', compute='_compute_is_rejection', store=True,
    )

    @api.depends('decision')
    def _compute_is_rejection(self):
        for rec in self:
            rec.is_rejection = (rec.decision == 'rejected')

    def name_get(self):
        result = []
        for rec in self:
            decision_label = dict(self._fields['decision'].selection).get(rec.decision, rec.decision)
            date_str = rec.date.strftime('%Y-%m-%d %H:%M') if rec.date else ''
            result.append((rec.id, f"{rec.user_id.name} – {decision_label} ({date_str})"))
        return result
