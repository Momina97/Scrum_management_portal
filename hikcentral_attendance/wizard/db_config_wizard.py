from odoo import models, fields, api, _
from odoo.exceptions import UserError


class HikCentralDbConfigWizard(models.TransientModel):
    _name = 'hik.central.db.config.wizard'
    _description = 'HikCentral Database Configuration Wizard'

    name = fields.Char('Configuration Name', required=True)
    host = fields.Char('Database Host', required=True)
    port = fields.Integer('Database Port', required=True, default=5432)
    database = fields.Char('Database Name', required=True)
    schema = fields.Char('Schema', default='public')
    table_name = fields.Char('Table Name', required=True, default='attendance_data')
    username = fields.Char('Database Username', required=True)
    password = fields.Char('Database Password', required=True)
    timezone = fields.Selection([
        ('Asia/Karachi', 'Pakistan (Asia/Karachi)'),
        ('UTC', 'UTC'),
        ('Asia/Kolkata', 'India (Asia/Kolkata)'),
        ('Asia/Dubai', 'UAE (Asia/Dubai)'),
        ('Europe/London', 'UK (Europe/London)'),
        ('US/Eastern', 'US Eastern'),
        ('US/Central', 'US Central'),
        ('US/Pacific', 'US Pacific'),
        ('Australia/Sydney', 'Australia (Sydney)'),
    ], string='Timezone', required=True, default='Asia/Karachi',
       help='Timezone to use for the database connection. This ensures timestamps are preserved correctly.')
    
    def action_create_config(self):
        config = self.env['hik.central.db.config'].create({
            'name': self.name,
            'host': self.host,
            'port': self.port,
            'database': self.database,
            'schema': self.schema,
            'table_name': self.table_name,
            'username': self.username,
            'password': self.password,
            'timezone': self.timezone,
        })
        
        return {
            'name': _('Database Configuration'),
            'view_mode': 'form',
            'res_model': 'hik.central.db.config',
            'res_id': config.id,
            'type': 'ir.actions.act_window',
        }
        
    def action_test_connection(self):
        config = self.env['hik.central.db.config'].new({
            'name': self.name,
            'host': self.host,
            'port': self.port,
            'database': self.database,
            'schema': self.schema,
            'table_name': self.table_name,
            'username': self.username,
            'password': self.password,
            'timezone': self.timezone,
        })
        
        return config.test_connection()
