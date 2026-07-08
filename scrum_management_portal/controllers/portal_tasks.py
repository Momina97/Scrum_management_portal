# -*- coding: utf-8 -*-
import logging
from odoo import http
from odoo.http import request
from odoo.exceptions import AccessError, ValidationError
from odoo.addons.portal.controllers.portal import CustomerPortal

_logger = logging.getLogger(__name__)


class ScrumPortalTasks(CustomerPortal):

    # ----------------------------------------------------------
    # HELPER
    # ----------------------------------------------------------

    def _get_task_or_404(self, project_id, task_id, check_parent=None):
        task = request.env['project.task'].sudo().browse(task_id)

        if not task.exists():
            return None

        if task.project_id.id != project_id:
            return None

        user_partner = request.env.user.partner_id
        project = request.env['project.project'].sudo().search([
            ('id', '=', project_id),
            ('message_partner_ids', 'in', [user_partner.id]),
        ], limit=1)
        if not project.exists():
            return None

        if check_parent is not None and (
            not task.parent_id or task.parent_id.id != check_parent
        ):
            return None

        return task

    # ----------------------------------------------------------
    # TASK DETAIL
    # ----------------------------------------------------------

    @http.route(['/my/scrum/projects/<int:project_id>/tasks/<int:task_id>'],
                type='http', 
                auth='user', 
                website=True, 
                methods=['GET']
                )
    
    def portal_task_detail(self, project_id, task_id, **kw):
        _logger.warning("=== TASK DETAIL CALLED === project_id=%s task_id=%s", project_id, task_id)

        task = self._get_task_or_404(project_id, task_id)

        if not task:
            return request.not_found()

        subtasks = request.env['project.task'].sudo().search([
            ('parent_id', '=', task.id),
        ])

        # Fetch timesheets for this task
        timesheets = request.env['account.analytic.line'].sudo().search([
            ('task_id', '=', task.id),
        ], order='date desc')

        # Get the portal user's own employee record for logging time
        employee = request.env['hr.employee'].sudo().search([
            ('user_id', '=', request.env.user.id),
        ], limit=1)

        values = {
            'project': task.project_id,
            'task': task,
            'subtasks': subtasks,
            'timesheets': timesheets,
            'employee': employee,
            'page_name': 'scrum_task',
            'active_tab': kw.get('tab', 'subtasks'),
        }
        return request.render('scrum_management_portal.portal_task_detail', values)

    # ----------------------------------------------------------
    # SUBTASK CREATE -  GET (show form)
    # ----------------------------------------------------------

    @http.route(
        ['/my/scrum/projects/<int:project_id>/tasks/<int:task_id>/subtask/new'],
        type='http', auth='user', website=True, methods=['GET']
    )
    def portal_subtask_new(self, project_id, task_id, **kw):
        _logger.warning("=== SUBTASK NEW GET === project_id=%s task_id=%s", project_id, task_id)

        task = self._get_task_or_404(project_id, task_id)

        if not task:
            return request.not_found()

        values = {
            'project': task.project_id,
            'task': task,
            'error': kw.get('error'),
            'page_name': 'scrum_subtask_new',
        }
        return request.render('scrum_management_portal.portal_subtask_new', values)

    # ----------------------------------------------------------
    # SUBTASK CREATE — POST (handle submission)
    # ----------------------------------------------------------

    @http.route(
        ['/my/scrum/projects/<int:project_id>/tasks/<int:task_id>/subtask/new'],
        type='http', auth='user', website=True, methods=['POST']
    )
    def portal_subtask_new_post(self, project_id, task_id, **kw):
        task = self._get_task_or_404(project_id, task_id)

        if not task:
            return request.not_found()

        subtask_name = kw.get('name', '').strip()

        if not subtask_name:
            values = {
                'project': task.project_id,
                'task': task,
                'error': 'Subtask name is required.',
                'page_name': 'scrum_subtask_new'
            }
            return request.render('scrum_management_portal.portal_subtask_new', values)

        try:
            request.env['project.task'].sudo().create({
                'name': subtask_name,
                'parent_id': task.id,
                'project_id': task.project_id.id,
            })
        except (ValidationError, AccessError) as e:
            values = {
                'project': task.project_id,
                'task': task,
                'error': str(e),
                'page_name': 'scrum_subtask_new'
            }
            return request.render('scrum_management_portal.portal_subtask_new', values)

        return request.redirect(
            '/my/scrum/projects/%d/tasks/%d' % (project_id, task_id)
        )

    # ----------------------------------------------------------
    # SUBTASK EDIT — GET (show form)
    # ----------------------------------------------------------

    @http.route(
        ['/my/scrum/projects/<int:project_id>/tasks/<int:task_id>/subtask/<int:subtask_id>/edit'],
        type='http', auth='user', website=True, methods=['GET']
    )
    def portal_subtask_edit(self, project_id, task_id, subtask_id, **kw):
        task = self._get_task_or_404(project_id, task_id)

        if not task:
            return request.not_found()

        subtask = self._get_task_or_404(project_id, subtask_id, check_parent=task.id)

        if not subtask:
            return request.not_found()

        stages = request.env['project.task.type'].sudo().search([
            ('project_type', '=', 'scrum'),
        ], order='sequence asc')

        values = {
            'project': task.project_id,
            'task': task,
            'subtask': subtask,
            'stages': stages,
            'error': kw.get('error'),
            'success': kw.get('success'),
            'page_name': 'scrum_subtask_edit',
        }
        return request.render('scrum_management_portal.portal_subtask_edit', values)

    # ----------------------------------------------------------
    # SUBTASK EDIT — POST (handle stage update)
    # ----------------------------------------------------------

    @http.route(
        ['/my/scrum/projects/<int:project_id>/tasks/<int:task_id>/subtask/<int:subtask_id>/edit'],
        type='http', 
        auth='user', 
        website=True, 
        methods=['POST']
    )
    def portal_subtask_edit_post(self, project_id, task_id, subtask_id, **kw):
        task = self._get_task_or_404(project_id, task_id)

        if not task:
            return request.not_found()

        subtask = self._get_task_or_404(project_id, subtask_id, check_parent=task.id)

        if not subtask:
            return request.not_found()

        new_stage_id = kw.get('stage_id')

        if not new_stage_id:
            stages = request.env['project.task.type'].sudo().search([
                ('project_type', '=', 'scrum'),
            ], order='sequence asc')
            values = {
                'project': task.project_id,
                'task': task,
                'subtask': subtask,
                'stages': stages,
                'error': 'Please select a stage.',
                'page_name': 'scrum_subtask_edit'
            }
            return request.render('scrum_management_portal.portal_subtask_edit', values)

        try:
            subtask.write({'stage_id': int(new_stage_id)})
        except (ValidationError, AccessError) as e:
            stages = request.env['project.task.type'].sudo().search([
                ('project_type', '=', 'scrum'),
            ], order='sequence asc')
            values = {
                'project': task.project_id,
                'task': task,
                'subtask': subtask,
                'stages': stages,
                'error': str(e),
                'page_name': 'scrum_subtask_edit'
            }
            return request.render('scrum_management_portal.portal_subtask_edit', values)

        return request.redirect(
            '/my/scrum/projects/%d/tasks/%d' % (project_id, task_id)
        )
    
   