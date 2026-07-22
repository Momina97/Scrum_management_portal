from odoo import http, _
from odoo.http import request
from odoo.exceptions import ValidationError, UserError, AccessError
from odoo.addons.hr_holidays_portal.controllers.portal import TimeOffPortal


class TimeOffFormPortal(TimeOffPortal):

    def _get_leave_sudo(self, leave_id, employee):
        leave = request.env['hr.leave'].sudo().browse(leave_id)
        if not leave.exists() or leave.employee_id.id != employee.id:
            raise AccessError(_("You do not have access to this leave request."))
        return leave

    @http.route('/my/timeoff/new',
                type='http', auth='user', website=True)
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
                leave_type = request.env['hr.leave.type'].sudo().browse(leave_type_id)
                has_allocation = leave_type.requires_allocation == 'no' or leave_type.with_context(
                    employee_id=employee.id
                ).has_valid_allocation
                if not has_allocation:
                    return self._render_timeoff_error(
                        _("No Leave Allocation Available"),
                        _(
                            "You don't have a valid leave allocation for the selected leave "
                            "type and dates. Please contact HR to request an allocation, or "
                            "choose a different leave type."
                        ),
                        back_url='/my/timeoff/new',
                        back_label='Back to Form',
                    )
                from datetime import datetime
                try:
                    d_from = datetime.strptime(date_from, '%Y-%m-%d').date()
                    d_to = datetime.strptime(date_to, '%Y-%m-%d').date()
                except Exception:
                    d_from = d_to = None
                overlapping = 0
                if d_from and d_to:
                    overlapping = request.env['hr.leave'].sudo().search_count([
                        ('employee_id', '=', employee.id),
                        ('state', 'in', ['confirm', 'validate1', 'validate']),
                        ('date_from', '<=', d_to),
                        ('date_to', '>=', d_from),
                    ])
                if overlapping:
                    return self._render_timeoff_error(
                        _("Leave Already Requested"),
                        _(
                            "You have already submitted a leave request that overlaps with "
                            "these dates. Please check your existing requests before applying again."
                        ),
                        back_url='/my/timeoff/requests',
                        back_label='View My Requests',
                    )
                cr = request.env.cr
                try:
                    with cr.savepoint():
                        leave = request.env['hr.leave'].sudo().create({
                            'holiday_status_id': leave_type_id,
                            'employee_id':       employee.id,
                            'request_date_from': date_from,
                            'request_date_to':   date_to,
                            'state':             'confirm',
                            'name':              description,
                        })
                        leave.flush_recordset()
                    return request.redirect('/my/timeoff/%d?submitted=1' % leave.id)
                except (ValidationError, UserError) as e:
                    msg = str(e).strip()
                    title = _("Cannot Submit Request")
                    if 'no valid allocation' in msg or 'not have any allocation' in msg:
                        title = _("No Leave Allocation Available")
                        msg = _(
                            "You don't have a valid leave allocation covering these dates for "
                            "the selected leave type. Please contact HR to request an allocation, "
                            "or choose a different leave type."
                        )
                    elif 'already booked' in msg or 'overlaps' in msg:
                        title = _("Leave Already Requested")
                        msg = _(
                            "You have already submitted a leave request that overlaps with "
                            "these dates. Please check your existing requests before applying again."
                        )
                    return self._render_timeoff_error(
                        title,
                        msg,
                        back_url='/my/timeoff/new',
                        back_label='Back to Form',
                    )
                except Exception as e:
                    return self._render_timeoff_error(
                        _("Cannot Submit Request"),
                        str(e),
                        back_url='/my/timeoff/new',
                        back_label='Back to Form',
                    )

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