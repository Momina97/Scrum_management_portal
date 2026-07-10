from odoo import fields, models

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    x_is_portal_approver = fields.Boolean(
        string = 'Portal Leave Approver',
        default = False,
    )