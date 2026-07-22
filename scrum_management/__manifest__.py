{
    'name': "Odoo 18 Scrum Integration",
    'summary': "Agile Project Management for Odoo",
    'author': "Cymax Technologies",
    'version': '18.0.1.4',   # bumped from 1.3 → triggers pre-migrate.py
    'depends': [
        'project',
        'mail',
        'web',
        'hr_timesheet',
        'sale_management',
    ],

    'data': [
        'security/ir.model.access.csv',
        'security/scrum_security.xml',
        'data/mail_templates.xml',
        'data/scrum_data.xml',
        'data/sprint_stage_data.xml',
        'data/ir_cron_data.xml',

        # Wizards
        'wizard/sprint_details_wizard_view.xml',
        'wizard/scrum_bulk_task_wizard_view.xml',   # ← NEW clean wizard views

        # Views
        'views/project_project_views.xml',
        'views/project_task_type_views.xml',
        'views/sprint_stage_views.xml',
        'views/project_scrum_sprint_views.xml',
        'views/sprint_dod.xml',
        'views/project_scrum_task_views.xml',
        'views/project_scrum_sp_config_views.xml',
        'views/project_scrum_release_views.xml',
        'views/project_scrum_meeting_views.xml',
        'views/scrum_dashboard_views.xml',
        'views/scrum_project_dashboard_view.xml',

        # Menus (always last)
        'views/scrum_menus.xml',
    ],

    'assets': {
        'web.assets_backend': [
            # CSS
            'scrum_management/static/src/css/scrum_style.css',
            'scrum_management/static/src/css/loader.css',
            'scrum_management/static/src/css/scrum_bulk_actions.css',
            'scrum_management/static/src/css/scrum_bar_bulk_action_responsive.css',
            'scrum_management/static/src/css/scrum_dashboard.css',

            # JS  — scrum_task_list.js now contains ALL bulk-action logic.
            #       scrum_bulk_actions.js is DELETED.
            'scrum_management/static/src/js/scrum_client_action.js',
            'scrum_management/static/src/js/delete_confirmation.js',
            'scrum_management/static/src/js/scrum_task_list.js',

            # XML — scrum_bulk_actions.xml is DELETED (logic is inline in JS).
            'scrum_management/static/src/xml/scrum_client_action.xml',
            'scrum_management/static/src/xml/scrum_task_list.xml',       
            'scrum_management/static/src/js/velocity_chart.js',
            'scrum_management/static/src/xml/velocity_chart.xml',
            'scrum_management/static/src/js/burndown_chart.js',
            'scrum_management/static/src/xml/burndown_chart.xml',
        ],
    },

    'installable': True,
    'application': True,
}