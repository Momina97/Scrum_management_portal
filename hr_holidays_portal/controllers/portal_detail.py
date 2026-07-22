from odoo import http, _
from odoo.http import request
from odoo.exceptions import AccessError
from odoo.addons.hr_holidays_portal.controllers.portal import TimeOffPortal


class TimeOffDetailPortal(TimeOffPortal):

    def _get_leave_sudo(self, leave_id, employee):
        leave = request.env['hr.leave'].sudo().browse(leave_id)
        if not leave.exists() or leave.employee_id.id != employee.id:
            raise AccessError(_("You do not have access to this leave request."))
        return leave

    @http.route('/my/timeoff/<int:leave_id>',
                type='http', auth='user', website=True)
    def portal_timeoff_detail(self, leave_id, **kw):
        employee = self._get_employee_sudo()
        if not employee:
            return request.render('hr_holidays_portal.portal_no_employee', {})

        try:
            leave = self._get_leave_sudo(leave_id, employee)
        except AccessError:
            return request.render('website.403')

        submitted = kw.get('submitted') == '1'

        return request.render('hr_holidays_portal.portal_timeoff_detail', {
            'employee':  employee,
            'leave':     leave,
            'submitted': submitted,
            'page_name': 'timeoff_detail',
        })

    @http.route('/my/timeoff/<int:leave_id>/cancel',
                type='http', auth='user', website=True, methods=['POST'])
    def portal_timeoff_cancel(self, leave_id, **kw):
        employee = self._get_employee_sudo()
        if not employee:
            return request.redirect('/my/timeoff')

        try:
            leave = self._get_leave_sudo(leave_id, employee)
        except AccessError:
            return request.redirect('/my/timeoff')

        if leave.state in ('draft', 'confirm', 'validate1'):
            leave.action_refuse()

        return request.redirect('/my/timeoff/%d' % leave_id)