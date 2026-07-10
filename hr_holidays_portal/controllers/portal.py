from odoo import http, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.exceptions import ValidationError, AccessError, UserError

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
    
    @http.route(['/my/timeoff', '/my/timeoff/page/<int:page>'],
                type = 'http',
                auth = 'user',
                website = True
                )
    def portal_my_timeoff(self, page = 1, **kw):
        page = int(page)
        employee = self._get_employee_sudo()

        if not employee:
            return request.render('hr_holidays_portal.portal_no_employee', {})
        
        domain = [('employee_id', '=' , employee.id)]
        Leave = request.env['hr.leave'].sudo()

        leave_count = Leave.search_count(domain)
        pager = portal_pager(
            url ='/my/timeoff',
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
            balance[lt_id]['remaining'] = (
                balance[lt_id]['allocated'] - balance[lt_id]['taken']
            )

        # --- Team leads: fetch their team's leaves ---
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

        return request.render('hr_holidays_portal.portal_my_timeoff', {
            'employee': employee,
            'leaves': leaves,
            'pager': pager,
            'balance': list(balance.values()),
            'is_approver': is_approver,
            'team_leaves': team_leaves,
            'page_name': 'timeoff',
        })
    
    @http.route('/my/timeoff/new', 
            type='http', 
            auth='user', 
            website=True
            )
    def portal_timeoff_new(self, **post):
        employee = self._get_employee_sudo()

        if not employee:
            return request.render('hr_holidays_portal.portal_no_employee', {})

        leave_types = request.env['hr.leave.type'].sudo().search([
            ('active', '=', True),
        ])

        if post.get('leave_type_id'):
            errors = {}
            leave_type_id = int(post.get('leave_type_id', 0))
            date_from     = post.get('date_from', '').strip()
            date_to       = post.get('date_to', '').strip()
            description   = post.get('description', '').strip()

            if not leave_type_id:
                errors['leave_type_id'] = _("Please select a leave type.")
            if not date_from:
                errors['date_from'] = _("Please set the start date.")
            if not date_to:
                errors['date_to'] = _("Please set the end date.")
            if not description:
                errors['description'] = _("Please provide a reason for your leave.")

            if not errors:
                try:
                    leave = request.env['hr.leave'].sudo().with_context(
                        leave_fast_create=True
                    ).create({
                        'holiday_status_id': leave_type_id,
                        'employee_id': employee.id,
                        'request_date_from': date_from,
                        'request_date_to': date_to,
                        'state': 'confirm',
                        'name': description,
                    })
                except (ValidationError, UserError) as e:
                    errors['general'] = str(e)
                    return request.render('hr_holidays_portal.portal_timeoff_new', {
                        'employee': employee,
                        'leave_types': leave_types,
                        'post': post,
                        'errors': errors,
                        'page_name': 'timeoff_new',
                    })
                except Exception as e:
                    errors['general'] = str(e)
                    return request.render('hr_holidays_portal.portal_timeoff_new', {
                        'employee': employee,
                        'leave_types': leave_types,
                        'post': post,
                        'errors': errors,
                        'page_name': 'timeoff_new',
                    })
                return request.redirect('/my/timeoff/%d?submitted=1' % leave.id)

            return request.render('hr_holidays_portal.portal_timeoff_new', {
                'employee':    employee,
                'leave_types': leave_types,
                'post':        post,
                'errors':      errors,
                'page_name':   'timeoff_new',
            })

        return request.render('hr_holidays_portal.portal_timeoff_new', {
            'employee':    employee,
            'leave_types': leave_types,
            'post':        {},
            'errors':      {},
            'page_name':   'timeoff_new',
        })

    @http.route('/my/timeoff/<int:leave_id>', 
                type='http', 
                auth='user', 
                website=True
                )
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

    @http.route(
        '/my/timeoff/<int:leave_id>/cancel',
                type='http', 
                auth='user', 
                website=True, 
                methods=['POST']
    )
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
    
    @http.route('/my/timeoff/<int:leave_id>/approve',
            type='http', 
            auth='user', 
            website=True, 
            methods=['POST']
            )
    def portal_timeoff_approve(self, leave_id, **kw):
        employee = self._get_employee_sudo()

        if not employee or not employee.x_is_portal_approver:
            return request.redirect('/my/timeoff')

        leave = request.env['hr.leave'].sudo().browse(leave_id)
        if not leave.exists():
            return request.redirect('/my/timeoff')

        # Check this leave belongs to one of the approver's team members
        team_members = request.env['hr.employee'].sudo().search([
            ('parent_id', '=', employee.id),
        ])
        if leave.employee_id.id not in team_members.ids:
            return request.redirect('/my/timeoff')

        if leave.state == 'confirm':
            leave.write({'state': 'validate1'})

        return request.redirect('/my/timeoff')

    @http.route(
        '/my/timeoff/<int:leave_id>/refuse',
        type='http', auth='user', website=True, methods=['POST']
    )
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

        if leave.state in ('confirm', 'validate1'):
            leave.action_refuse()

        return request.redirect('/my/timeoff')