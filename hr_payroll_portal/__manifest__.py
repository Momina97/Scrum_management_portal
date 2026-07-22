# -*- coding: utf-8 -*-
{
    'name': 'Payroll Portal',
    'version': '18.0.1.0.0',
    'category': 'Human Resources/Payroll',
    'summary': 'Allow portal users to view their payslips',
    'depends': [
        'hr_payroll',
        'portal',
        'hr_holidays_portal',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/portal_layout.xml',
        'views/portal_payslip_list.xml',
        'views/portal_payslip_detail.xml',
        'views/portal_payslip_dashboard.xml',
        'views/portal_no_employee.xml',
    ],
    'assets': {
    'web.assets_frontend': [
        'hr_payroll_portal/static/src/css/portal_styles.css',
        'hr_payroll_portal/static/src/css/portal_dashboard.css'
    ],
},

    'installable': True,
    'application': False,
    'license': 'OEEL-1',
}