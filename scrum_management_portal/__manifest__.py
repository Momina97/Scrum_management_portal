{
    'name': "Scrum Management - Portal",
    'summary': "Portal access for clients to view and manage their Scrum projects",
    'author': "Cymax Technologies",
    'version': '18.0.1.0',

    'depends': [
        'portal',
        'scrum_management',
    ],

    'data': [
        'security/ir.model.access.csv',
        'security/scrum_portal_security.xml',
        'views/portal_templates.xml',
        'views/portal_timesheets_templates.xml'
    ],

    'assets': {
        'web.assets_frontend': [
            'scrum_management_portal/static/src/css/portal_scrum.css',
        ],
    },

    'installable': True,
    'application': True,
}