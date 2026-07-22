from odoo import http, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.exceptions import AccessError, ValidationError, UserError


class TimeOffPortal(CustomerPortal):

    def _get_employee_sudo(self):
        return request.env['hr.employee'].sudo().search(
            [('user_id', '=', request.env.user.id)],
            limit=1,
        )
    
    def _get_leave_sudo(self, leave_id, employee):
        leave = request.env['hr.leave'].sudo().browse(leave_id)
        if not leave.exists() or leave.employee_id.id != employee.id:
            raise AccessError(_("You do not have access to this leave request."))
        return leave

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'leave_count' in counters:
            employee = self._get_employee_sudo()
            if employee:
                values['leave_count'] = request.env['hr.leave'].sudo().search_count(
                    [('employee_id', '=', employee.id)]
                )
            else:
                values['leave_count'] = 0
        return values

    def _get_balance(self, employee):
        Leave = request.env['hr.leave'].sudo()
        allocations = request.env['hr.leave.allocation'].sudo().search([
            ('employee_id', '=', employee.id),
            ('state', '=', 'validate'),
        ])

        balance = {}
        for alloc in allocations:
            lt_id = alloc.holiday_status_id.id
            if lt_id not in balance:
                balance[lt_id] = {
                    'name': alloc.holiday_status_id.name,
                    'allocated': 0,
                    'taken': 0,
                }
            balance[lt_id]['allocated'] += alloc.number_of_days

        taken_leaves = Leave.search([
            ('employee_id', '=', employee.id),
            ('state', 'in', ['validate1', 'validate']),
        ])
        for lv in taken_leaves:
            lt_id = lv.holiday_status_id.id
            if lt_id in balance:
                balance[lt_id]['taken'] += lv.number_of_days

        for lt_id in balance:
            remaining = balance[lt_id]['allocated'] - balance[lt_id]['taken']
            balance[lt_id]['remaining'] = remaining
            pct = int(min((remaining / balance[lt_id]['allocated'] * 100) if balance[lt_id]['allocated'] else 0, 100))
            balance[lt_id]['bar_style'] = 'width: %s%%' % pct

        return list(balance.values())

    # ── DASHBOARD ──
    @http.route(['/my/timeoff'],
                type='http', auth='user', website=True)
    def portal_my_timeoff(self, **kw):
        employee = self._get_employee_sudo()
        if not employee:
            return request.render('hr_holidays_portal.portal_no_employee', {})

        balance = self._get_balance(employee)
        is_approver = bool(employee.x_is_portal_approver)

        to_approve = []
        if is_approver:
            team_members = request.env['hr.employee'].sudo().search([
                ('parent_id', '=', employee.id),
            ])
            if team_members:
                to_approve = request.env['hr.leave'].sudo().search([
                    ('employee_id', 'in', team_members.ids),
                    ('state', '=', 'confirm'),
                ], order='write_date desc')

        waiting = request.env['hr.leave'].sudo().search([
            ('employee_id', '=', employee.id),
            ('state', 'in', ['confirm', 'validate1']),
        ], order='write_date desc')

        return request.render('hr_holidays_portal.portal_my_timeoff', {
            'employee':     employee,
            'balance':      balance,
            'page_name':    'timeoff',
            'is_approver':  is_approver,
            'to_approve':   to_approve,
            'waiting':      waiting,
        })

    # ── REQUESTS LIST ──
    @http.route(['/my/timeoff/requests', '/my/timeoff/requests/page/<int:page>'],
                type='http', auth='user', website=True)
    def portal_timeoff_requests(self, page=1, **kw):
        page = int(page)
        employee = self._get_employee_sudo()
        if not employee:
            return request.render('hr_holidays_portal.portal_no_employee', {})

        Leave = request.env['hr.leave'].sudo()
        domain = [('employee_id', '=', employee.id)]

        leave_count = Leave.search_count(domain)
        pager = portal_pager(
            url='/my/timeoff/requests',
            url_args={},
            total=leave_count,
            page=page,
            step=10,
        )
        leaves = Leave.search(
            domain,
            order='write_date desc',
            limit=10,
            offset=pager['offset'],
        )

        is_approver = employee.x_is_portal_approver
        team_leaves = []
        if is_approver:
            team_members = request.env['hr.employee'].sudo().search([
                ('parent_id', '=', employee.id),
            ])
            if team_members:
                team_leaves = Leave.search([
                    ('employee_id', 'in', team_members.ids),
                ], order='write_date desc')

        balance = self._get_balance(employee)

        return request.render('hr_holidays_portal.portal_timeoff_requests', {
            'employee':    employee,
            'leaves':      leaves,
            'pager':       pager,
            'is_approver': is_approver,
            'team_leaves': team_leaves,
            'balance':     balance,
            'page_name':   'timeoff_requests',
        })

    def _render_timeoff_error(self, error_title, error_message, back_url='/my/timeoff', back_label='Go Back'):
        return request.render('hr_holidays_portal.portal_timeoff_error', {
            'error_title':   error_title,
            'error_message': error_message,
            'back_url':      back_url,
            'back_label':    back_label,
            'page_name':     'timeoff',
        })

    # ── APPROVE ──
    @http.route('/my/timeoff/<int:leave_id>/approve',
                type='http', auth='user', website=True, methods=['POST'])
    def portal_timeoff_approve(self, leave_id, **kw):
        employee = self._get_employee_sudo()
        if not employee or not employee.x_is_portal_approver:
            return request.redirect('/my/timeoff')

        leave = request.env['hr.leave'].sudo().browse(leave_id)
        if not leave.exists():
            return request.redirect('/my/timeoff')

        team_members = request.env['hr.employee'].sudo().search([
            ('parent_id', '=', employee.id),
        ])
        if leave.employee_id.id not in team_members.ids:
            return request.redirect('/my/timeoff')

        if leave.state == 'confirm':
            try:
                with request.env.cr.savepoint():
                    leave.write({'state': 'validate1'})
                    leave.flush_recordset()
            except (ValidationError, UserError) as e:
                return self._render_timeoff_error(
                    _("Cannot Approve Request"),
                    _(
                        "This leave request could not be approved: %s The request remains "
                        "pending and must not be approved until the issue is resolved."
                    ) % str(e).strip(),
                    back_url='/my/timeoff/requests#team-requests',
                    back_label='Back to Team Requests',
                )

        return request.redirect('/my/timeoff/requests#team-requests')

    # ── REFUSE ──
    @http.route('/my/timeoff/<int:leave_id>/refuse',
                type='http', auth='user', website=True, methods=['POST'])
    def portal_timeoff_refuse(self, leave_id, **kw):
        employee = self._get_employee_sudo()
        if not employee or not employee.x_is_portal_approver:
            return request.redirect('/my/timeoff')

        leave = request.env['hr.leave'].sudo().browse(leave_id)
        if not leave.exists():
            return request.redirect('/my/timeoff')

        team_members = request.env['hr.employee'].sudo().search([
            ('parent_id', '=', employee.id),
        ])
        if leave.employee_id.id not in team_members.ids:
            return request.redirect('/my/timeoff')

        try:
            with request.env.cr.savepoint():
                if leave.state in ('confirm', 'validate1'):
                    leave.action_refuse()
                leave.flush_recordset()
        except (ValidationError, UserError) as e:
            return self._render_timeoff_error(
                _("Cannot Refuse Request"),
                _("This leave request could not be refused: %s") % str(e).strip(),
                back_url='/my/timeoff/requests#team-requests',
                back_label='Back to Team Requests',
            )

        return request.redirect('/my/timeoff/requests#team-requests')