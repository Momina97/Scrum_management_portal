from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ProductRequisitionRejectWizard(models.TransientModel):
    _name = 'product.requisition.reject.wizard'
    _description = 'Product Requisition Reject Wizard'

    requisition_id = fields.Many2one(
        'product.requisition', string='Requisition', required=True,
    )
    reason = fields.Text(
        string='Rejection Reason',
        required=True,
        placeholder="Please provide a clear reason for rejection...",
    )

    # Read-only context fields shown in the wizard for easy reference
    requester_name = fields.Char(
        related='requisition_id.user_id.name',
        string='Requested By',
        readonly=True,
    )
    current_step = fields.Char(
        related='requisition_id.current_step_name',
        string='Current Step',
        readonly=True,
    )
    department_name = fields.Char(
        related='requisition_id.department_id.name',
        string='Department',
        readonly=True,
    )

    @api.constrains('reason')
    def _check_reason_length(self):
        for wizard in self:
            if wizard.reason and len(wizard.reason.strip()) < 10:
                raise UserError(
                    _("Please provide a more detailed rejection reason (at least 10 characters).")
                )

    def action_confirm_reject(self):
        self.ensure_one()
        if not self.reason or not self.reason.strip():
            raise UserError(_("Please provide a reason for rejection."))
        if len(self.reason.strip()) < 10:
            raise UserError(
                _("Please provide a more detailed rejection reason (at least 10 characters).")
            )

        self.requisition_id._do_reject(self.reason.strip())

        return {
            'type': 'ir.actions.client',
            'tag':  'display_notification',
            'params': {
                'title':   _('Requisition Rejected'),
                'message': _('The requisition has been rejected and the requester has been notified.'),
                'type':    'warning',
                'sticky':  False,
            },
        }
