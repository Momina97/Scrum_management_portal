{
    'name': 'Time Off Portal',
    'version': '18.0.1.0.0',
    'category': 'Human Resources/Time Off',
    'summary': 'Allow portal users to request and track time off',
    'depends': [
        'hr_holidays',
        'portal',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/hr_employee_views.xml',
        'views/portal_layout.xml',
        'views/portal_timeoff_requests.xml',
        'views/portal_timeoff_list.xml',
        'views/portal_timeoff_form.xml',
        'views/portal_timeoff_detail.xml',
        'views/portal_no_employee.xml',
        'views/portal_timeoff_error.xml'
    ],
    'assets': {
    'web.assets_frontend': [
        'hr_holidays_portal/static/src/css/portal_styles.css',
    ],
},
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}