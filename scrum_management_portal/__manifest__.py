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
        'views/scrum_backlog.xml',
        'views/scrum_breadcrumbs.xml',
        'views/scrum_portal_home.xml',
        'views/scrum_project_detail.xml',
        'views/scrum_projects_list.xml',
        'views/scrum_sprint_detail.xml',
        'views/scrum_subtask_edit.xml',
        'views/scrum_subtask_new.xml',
        'views/scrum_task_detail.xml',
        'views/scrum_timesheet_edit.xml',
        'views/scrum_timesheet_new.xml',
    ],

    'assets': {
        'web.assets_frontend': [
            'scrum_management_portal/static/src/css/scrum_base.css',
            'scrum_management_portal/static/src/css/scrum_cards.css',
            'scrum_management_portal/static/src/css/scrum_task_detail.css',
        ],
    },

    'installable': True,
    'application': True,
}