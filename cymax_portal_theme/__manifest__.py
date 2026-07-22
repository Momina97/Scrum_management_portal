# -*- coding: utf-8 -*-
{
    'name': 'Cymax Portal Theme',
    'version': '18.0.1.0.0',
    'summary': 'Custom portal homepage theme for Cymax modules',
    'category': 'Portal',
    'author': 'Cymax Technologies',
    'depends': ['portal', 'web'],
    'data': [
        'views/portal_home.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'cymax_portal_theme/static/src/css/portal_theme.css',
        ],
    },
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}