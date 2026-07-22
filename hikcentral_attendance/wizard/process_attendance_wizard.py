from odoo import models, fields, api, _
from odoo.exceptions import UserError

class ProcessAttendanceWizard(models.TransientModel):
    _name = 'hik.process.attendance.wizard'
    _description = 'Process Attendance Wizard'
    
    def _default_attendance_ids(self):
        return self.env.context.get('active_ids', [])
    
    attendance_ids = fields.Many2many('hik.attendance.record', string='Attendance Records', 
                                      default=_default_attendance_ids)
    action_type = fields.Selection([
        ('map_employee', 'Map Employees'),
        ('create_attendance', 'Create Attendance Records'),
    ], string='Action', required=True, default='map_employee')
    
    def action_process(self):
        if not self.attendance_ids:
            raise UserError(_("No attendance records selected."))
        
        if self.action_type == 'map_employee':
            self.attendance_ids.action_map_employee()
            message = _("Employee mapping process completed.")
        else:  # create_attendance
            self.attendance_ids.action_create_attendance()
            message = _("Attendance creation process completed.")
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Process Completed'),
                'message': message,
                'type': 'success',
                'sticky': False,
            }
        }
