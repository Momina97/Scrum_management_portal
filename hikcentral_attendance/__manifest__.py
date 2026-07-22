{
    'name': 'HikCentral Attendance Integration',
    'version': '1.0.0',
    'summary': 'Integrate HikCentral biometric attendance system with Odoo attendance management',
    'author': 'wahabTanoli',
    'website': 'https://cymaxtech.com',
    'license': 'LGPL-3',
    'category': 'Human Resources/Attendance',
    'depends': ['base', 'hr', 'hr_attendance'],
    'data': [
        'security/ir.model.access.csv',
        'views/hik_db_config_views.xml',
        'views/hik_attendance_record_views.xml',
        'views/process_attendance_wizard_views.xml',
        'views/set_sync_date_wizard_views.xml',
        'views/hr_employee_views.xml',
        'data/ir_cron_data.xml',
    ],
    'external_dependencies': {
        'python': ['psycopg2'],
    },
    'installable': True,
    'application': True,
}
