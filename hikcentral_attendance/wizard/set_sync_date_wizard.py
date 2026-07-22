from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import datetime, timedelta


class SetSyncDateWizard(models.TransientModel):
    _name = 'hik.set.sync.date.wizard'
    _description = 'Set Synchronization Date Wizard'
    
    config_id = fields.Many2one('hik.central.db.config', string='Database Configuration', required=True)
    current_date = fields.Datetime(string='Current Sync Date', readonly=True)
    new_date = fields.Datetime(string='New Sync Date', required=True)
    reset_type = fields.Selection([
        ('specific', 'Set to Specific Date/Time'),
        ('days', 'Go Back Number of Days'),
        ('reset', 'Reset Completely (Import All)')
    ], string='Reset Type', default='specific', required=True)
    days_back = fields.Integer(string='Days to Go Back', default=1)
    
    @api.onchange('reset_type')
    def _onchange_reset_type(self):
        """Update the new_date field based on the selected reset type"""
        if self.reset_type == 'specific':
            # Keep the user-entered date
            pass
        elif self.reset_type == 'days':
            # Set to current date minus specified days
            if self.current_date:
                self.new_date = self.current_date - timedelta(days=self.days_back)
            else:
                # Format the date in the same format as PostgreSQL timestamps
                now = datetime.now()
                self.new_date = now - timedelta(days=self.days_back)
        elif self.reset_type == 'reset':
            # Reset to False (None) to import all records
            self.new_date = False
    
    @api.onchange('days_back')
    def _onchange_days_back(self):
        """Update the new_date when days_back is changed"""
        if self.reset_type == 'days' and self.days_back:
            if self.current_date:
                self.new_date = self.current_date - timedelta(days=self.days_back)
            else:
                # Format the date in the same format as PostgreSQL timestamps
                now = datetime.now()
                self.new_date = now - timedelta(days=self.days_back)
    
    def action_set_sync_date(self):
        """Set the synchronization date to the selected value"""
        self.ensure_one()
        
        # Save the previous date for the message
        previous_date = self.config_id.last_sync_date
        
        # Set the new date
        if self.reset_type == 'reset':
            self.config_id.last_sync_date = False
            message = _('Synchronization date has been completely reset.')
        else:
            self.config_id.last_sync_date = self.new_date
            message = _(f'Synchronization date has been set to {self.new_date}.')
        
        if previous_date:
            message += _(' Previous date was: %s') % previous_date
            
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Sync Date Updated'),
                'message': message,
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window_close'
                }
            }
        }
