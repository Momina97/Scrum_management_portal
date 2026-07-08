import logging
from odoo import http
from odoo.http import request
from odoo.exceptions import AccessError, ValidationError
from odoo.addons.portal.controllers.portal import CustomerPortal

_logger = logging.getLogger(__name__)


class ScrumPortalTimesheets(CustomerPortal):

    # ----------------------------------------------------------
    # HELPERS
    # ----------------------------------------------------------

    def _get_task_for_timesheet(self, project_id, task_id):
        user_partner = request.env.user.partner_id
        project = request.env['project.project'].sudo().search([
            ('id', '=', project_id),
            ('message_partner_ids', 'in', [user_partner.id]),
        ], limit=1)
        if not project.exists():
            return None
        task = request.env['project.task'].sudo().browse(task_id)
        if not task.exists() or task.project_id.id != project_id:
            return None
        return task

    def _get_employee(self):
        return request.env['hr.employee'].sudo().search([
            ('user_id', '=', request.env.user.id),
        ], limit=1)

    def _get_timesheet_or_404(self, task_id, timesheet_id):
        timesheet = request.env['account.analytic.line'].sudo().browse(timesheet_id)
        if not timesheet.exists():
            return None
        if timesheet.task_id.id != task_id:
            return None
        employee = self._get_employee()
        if not employee or timesheet.employee_id.id != employee.id:
            return None
        return timesheet

    # ----------------------------------------------------------
    # TIMESHEET CREATE — GET
    # ----------------------------------------------------------

    @http.route(
        ['/my/scrum/projects/<int:project_id>/tasks/<int:task_id>/timesheets/new'],
        type='http', auth='user', website=True, methods=['GET']
    )
    def portal_timesheet_new(self, project_id, task_id, **kw):
        task = self._get_task_for_timesheet(project_id, task_id)
        if not task:
            return request.not_found()

        employee = self._get_employee()
        if not employee:
            return request.redirect(
                '/my/scrum/projects/%d/tasks/%d?tab=timesheets' % (project_id, task_id)
            )

        values = {
            'project': task.project_id,
            'task': task,
            'employee': employee,
            'error': kw.get('error'),
            'page_name': 'scrum_task',
        }
        return request.render(
            'scrum_management_portal.portal_timesheet_new', values
        )

    # ----------------------------------------------------------
    # TIMESHEET CREATE — POST
    # ----------------------------------------------------------

    @http.route(
        ['/my/scrum/projects/<int:project_id>/tasks/<int:task_id>/timesheets/new'],
        type='http', auth='user', website=True, methods=['POST']
    )
    def portal_timesheet_new_post(self, project_id, task_id, **kw):
        task = self._get_task_for_timesheet(project_id, task_id)
        if not task:
            return request.not_found()

        employee = self._get_employee()
        if not employee:
            return request.redirect(
                '/my/scrum/projects/%d/tasks/%d?tab=timesheets' % (project_id, task_id)
            )

        date = kw.get('date', '').strip()
        hours = kw.get('unit_amount', '').strip()
        description = kw.get('name', '').strip()

        errors = []
        if not date:
            errors.append('Date is required.')
        if not hours:
            errors.append('Hours is required.')
        else:
            try:
                hours = float(hours)
                if hours <= 0:
                    errors.append('Hours must be greater than 0.')
            except ValueError:
                errors.append('Hours must be a valid number.')

        if errors:
            values = {
                'project': task.project_id,
                'task': task,
                'employee': employee,
                'error': ' '.join(errors),
                'page_name': 'scrum_task',
            }
            return request.render(
                'scrum_management_portal.portal_timesheet_new', values
            )

        try:
            request.env['account.analytic.line'].sudo().create({
                'task_id': task.id,
                'project_id': task.project_id.id,
                'employee_id': employee.id,
                'date': date,
                'unit_amount': hours,
                'name': description or '/',
            })
        except (ValidationError, AccessError) as e:
            values = {
                'project': task.project_id,
                'task': task,
                'employee': employee,
                'error': str(e),
                'page_name': 'scrum_task',
            }
            return request.render(
                'scrum_management_portal.portal_timesheet_new', values
            )

        return request.redirect(
            '/my/scrum/projects/%d/tasks/%d?tab=timesheets' % (project_id, task_id)
        )

    # ----------------------------------------------------------
    # TIMESHEET EDIT — GET
    # ----------------------------------------------------------

    @http.route(
        ['/my/scrum/projects/<int:project_id>/tasks/<int:task_id>/timesheets/<int:timesheet_id>/edit'],
        type='http', auth='user', website=True, methods=['GET']
    )
    def portal_timesheet_edit(self, project_id, task_id, timesheet_id, **kw):
        task = self._get_task_for_timesheet(project_id, task_id)
        if not task:
            return request.not_found()

        timesheet = self._get_timesheet_or_404(task_id, timesheet_id)
        if not timesheet:
            return request.not_found()

        values = {
            'project': task.project_id,
            'task': task,
            'timesheet': timesheet,
            'employee': timesheet.employee_id,
            'error': kw.get('error'),
            'page_name': 'scrum_task',
        }
        return request.render(
            'scrum_management_portal.portal_timesheet_edit', values
        )

    # ----------------------------------------------------------
    # TIMESHEET EDIT — POST
    # ----------------------------------------------------------

    @http.route(
        ['/my/scrum/projects/<int:project_id>/tasks/<int:task_id>/timesheets/<int:timesheet_id>/edit'],
        type='http', auth='user', website=True, methods=['POST']
    )
    def portal_timesheet_edit_post(self, project_id, task_id, timesheet_id, **kw):
        task = self._get_task_for_timesheet(project_id, task_id)
        if not task:
            return request.not_found()

        timesheet = self._get_timesheet_or_404(task_id, timesheet_id)
        if not timesheet:
            return request.not_found()

        date = kw.get('date', '').strip()
        hours = kw.get('unit_amount', '').strip()
        description = kw.get('name', '').strip()

        errors = []
        if not date:
            errors.append('Date is required.')
        if not hours:
            errors.append('Hours is required.')
        else:
            try:
                hours = float(hours)
                if hours <= 0:
                    errors.append('Hours must be greater than 0.')
            except ValueError:
                errors.append('Hours must be a valid number.')

        if errors:
            values = {
                'project': task.project_id,
                'task': task,
                'timesheet': timesheet,
                'employee': timesheet.employee_id,
                'error': ' '.join(errors),
                'page_name': 'scrum_task',
            }
            return request.render(
                'scrum_management_portal.portal_timesheet_edit', values
            )

        try:
            timesheet.sudo().write({
                'date': date,
                'unit_amount': hours,
                'name': description or '/',
            })
        except (ValidationError, AccessError) as e:
            values = {
                'project': task.project_id,
                'task': task,
                'timesheet': timesheet,
                'employee': timesheet.employee_id,
                'error': str(e),
                'page_name': 'scrum_task',
            }
            return request.render(
                'scrum_management_portal.portal_timesheet_edit', values
            )

        return request.redirect(
            '/my/scrum/projects/%d/tasks/%d?tab=timesheets' % (project_id, task_id)
        )