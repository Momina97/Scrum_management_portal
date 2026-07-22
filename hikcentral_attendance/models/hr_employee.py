from odoo import models, fields, api, _
from odoo.exceptions import UserError, AccessError

class HrEmployee(models.Model):
    _inherit = 'hr.employee'
    
    # Add the field to both hr.employee and hr.employee.public for proper access
    allow_odoo_attendance = fields.Boolean(
        string="Allow Manual Attendance",
        default=False,
        help="If checked, the employee will be able to use the Odoo interface to check in and check out. "
             "This is in addition to the global attendance settings."
    )
    
    @api.model
    def _get_hr_readable_fields(self):
        """Override to make allow_odoo_attendance readable in public contexts"""
        return super()._get_hr_readable_fields() | {'allow_odoo_attendance'}
    
    def _attendance_action_change(self, geo_information=None):
        """Override the check-in/check-out method to verify if the employee is allowed to use the Odoo interface.
        Employee can only use Odoo interface for attendance if both global setting and employee-specific setting are enabled.
        """
        self.ensure_one()
        
        # Only check the custom field if we're in the right context (not for system operations)
        # This prevents issues when the field is accessed in restricted contexts like public profiles
        if self.env.context.get('skip_attendance_check'):
            return super(HrEmployee, self)._attendance_action_change(geo_information=geo_information)
        
        # Check if employee is allowed to use Odoo interface for attendance
        # Use safe field access to handle different contexts
        allow_attendance = getattr(self, 'allow_odoo_attendance', False)
            
        if not allow_attendance:
            raise UserError(_("You are not allowed to register attendance through the Odoo interface. "
                             "Please use the biometric device for attendance."))
        
        # If employee is allowed, proceed with the standard check-in/check-out process
        return super(HrEmployee, self)._attendance_action_change(geo_information=geo_information)


class HrEmployeePublic(models.Model):
    _inherit = 'hr.employee.public'
    
    # Make the field available in public employee model too
    allow_odoo_attendance = fields.Boolean(
        string="Allow Manual Attendance",
        default=False,
        readonly=True,
        help="If checked, the employee will be able to use the Odoo interface to check in and check out."
    )
    
    @api.model
    def _get_hr_readable_fields(self):
        """Ensure allow_odoo_attendance is always readable in public contexts"""
        return super()._get_hr_readable_fields() | {'allow_odoo_attendance'}