from odoo import http
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal


class ScrumPortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)

        return values

    @http.route(['/my/scrum/projects'], 
                type='http', 
                auth='user', 
                website=True
                )
    def portal_my_projects(self, **kw):
        user_partner = request.env.user.partner_id
        projects = request.env['project.project'].sudo().search([
            ('project_type', '=', 'scrum'),
            ('message_partner_ids', 'in', [user_partner.id]),
        ])
        values = {
            'projects': projects,
            'page_name': 'scrum_projects',
        }
        return request.render('scrum_management_portal.portal_my_projects', values)

    def _get_portal_project_or_404(self, project_id):
        user_partner = request.env.user.partner_id
        project = request.env['project.project'].sudo().search([
            ('id', '=', project_id),
            ('message_partner_ids', 'in', [user_partner.id]),
        ], limit=1)
        if not project.exists():
            return None
        return project

    @http.route(['/my/scrum/projects/<int:project_id>'], 
                type='http', 
                auth='user', 
                website=True
                )
    def portal_project_detail(self, project_id, **kw):
        project = self._get_portal_project_or_404(project_id)
        if not project:
            return request.not_found()

        sprints = request.env['project.scrum.sprint'].sudo().search([
            ('project_id', '=', project.id),
        ])

        backlog_count = request.env['project.task'].sudo().search_count([
            ('project_id', '=', project.id),
            ('sprint_id', '=', False),
            ('parent_id', '=', False),
        ])

        values = {
            'project': project,
            'sprints': sprints,
            'backlog_count': backlog_count,
            'page_name': 'scrum_project',
        }
        return request.render('scrum_management_portal.portal_project_detail', values)


    @http.route(['/my/scrum/projects/<int:project_id>/sprints/<int:sprint_id>'],
            type='http',
            auth='user',
            website=True
            )
    def portal_sprint_detail(self, project_id, sprint_id, **kw):
        project = self._get_portal_project_or_404(project_id)
        if not project:
            return request.not_found()

        sprint = request.env['project.scrum.sprint'].sudo().browse(sprint_id)
        if not sprint.exists() or sprint.project_id.id != project.id:
            return request.not_found()

        tasks = request.env['project.task'].sudo().search([
            ('project_id', '=', project.id),
            ('sprint_id', '=', sprint.id),
            ('parent_id', '=', False),
        ])

        values = {
            'project': project,
            'sprint': sprint,
            'tasks': tasks,
            'page_name': 'scrum_sprint',
        }
        return request.render('scrum_management_portal.portal_sprint_detail', values)

    @http.route(['/my/scrum/projects/<int:project_id>/backlog'],
            type='http', 
            auth='user', 
            website=True
            )
    def portal_project_backlog(self, project_id, **kw):
        project = self._get_portal_project_or_404(project_id)
        if not project:
            return request.not_found()

        tasks = request.env['project.task'].sudo().search([
            ('project_id', '=', project.id),
            ('sprint_id', '=', False),
            ('parent_id', '=', False),
        ])

        task_subtask_counts = {}
        for task in tasks:
            task_subtask_counts[task.id] = request.env['project.task'].sudo().search_count([
                ('parent_id', '=', task.id),
            ])

        values = {
            'project': project,
            'tasks': tasks,
            'task_subtask_counts': task_subtask_counts,
            'page_name': 'scrum_backlog',
        }
        return request.render('scrum_management_portal.portal_project_backlog', values)