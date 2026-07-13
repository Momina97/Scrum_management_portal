# -*- coding: utf-8 -*-
{
    'name': 'Attendance Portal',
    'version': '18.0.1.0.0',
    'category': 'Human Resources/Attendances',
    'summary': 'Allow portal users to view their attendance and check in/out',
    'depends': [
        'hr_attendance',
        'portal',
        'hr_holidays_portal',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/portal_layout.xml',
        'views/portal_attendance_list.xml',
        'views/portal_no_employee.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}