from odoo import http, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.exceptions import AccessError
from datetime import date, datetime
import calendar


class AttendancePortal(CustomerPortal):

    def _get_employee_sudo(self):
        return request.env['hr.employee'].sudo().search(
            [('user_id', '=', request.env.user.id)],
            limit=1,
        )

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'attendance_count' in counters:
            employee = self._get_employee_sudo()
            if employee:
                values['attendance_count'] = request.env['hr.attendance'].sudo().search_count([
                    ('employee_id', '=', employee.id),
                ])
            else:
                values['attendance_count'] = 0
        return values

    @http.route(['/my/attendance', '/my/attendance/page/<int:page>'],
                type='http',
                auth='user',
                website=True
                )
    def portal_my_attendance(self, page=1, filter_year=None, filter_month=None, **kw):
        page = int(page)
        employee = self._get_employee_sudo()

        if not employee:
            return request.render('hr_attendance_portal.portal_no_employee', {})

        today = date.today()

        Attendance = request.env['hr.attendance'].sudo()

        # Build year list from all employee attendances
        all_years = Attendance.search([
            ('employee_id', '=', employee.id),
        ], order='check_in asc', limit=0)
        years = sorted(set(
            a.check_in.year for a in all_years if a.check_in
        ), reverse=True) or [today.year]

        # ---- Build date domain ----
        if filter_year is None and filter_month is None:
            date_domain = [
                ('check_in', '>=', '%s-%s-01 00:00:00' % (
                    today.year, str(today.month).zfill(2)
                )),
                ('check_in', '<=', '%s-%s-%s 23:59:59' % (
                    today.year,
                    str(today.month).zfill(2),
                    calendar.monthrange(today.year, today.month)[1]
                )),
            ]

        elif filter_year and filter_month:
            # Specific year + specific month
            year = int(filter_year)
            month = int(filter_month)
            last_day = calendar.monthrange(year, month)[1]
            date_domain = [
                ('check_in', '>=', '%s-%s-01 00:00:00' % (year, str(month).zfill(2))),
                ('check_in', '<=', '%s-%s-%s 23:59:59' % (
                    year, str(month).zfill(2), last_day
                )),
            ]

        elif filter_year and not filter_month:
            # Whole year, all months
            date_domain = [
                ('check_in', '>=', '%s-01-01 00:00:00' % filter_year),
                ('check_in', '<=', '%s-12-31 23:59:59' % filter_year),
            ]

        elif filter_month and not filter_year:
            # Specific month, but across ALL years the employee has records in
            month = int(filter_month)
            if not years:
                date_domain = [('id', '=', 0)]
            else:
                date_domain = ['|'] * (len(years) - 1)
                for y in years:
                    last_day = calendar.monthrange(y, month)[1]
                    date_domain += [
                        '&',
                        ('check_in', '>=', '%s-%s-01 00:00:00' % (y, str(month).zfill(2))),
                        ('check_in', '<=', '%s-%s-%s 23:59:59' % (
                            y, str(month).zfill(2), last_day
                        )),
                    ]

        else:
            date_domain = []

        domain = [('employee_id', '=', employee.id)] + date_domain

        attendance_count = Attendance.search_count(domain)
        pager = portal_pager(
            url='/my/attendance',
            url_args={
                'filter_year': filter_year or '',
                'filter_month': filter_month or '',
            },
            total=attendance_count,
            page=page,
            step=20,
        )
        attendances = Attendance.search(
            domain,
            order='check_in desc',
            limit=20,
            offset=pager['offset'],
        )

        months = [
            ('1', 'January'), ('2', 'February'), ('3', 'March'),
            ('4', 'April'), ('5', 'May'), ('6', 'June'),
            ('7', 'July'), ('8', 'August'), ('9', 'September'),
            ('10', 'October'), ('11', 'November'), ('12', 'December'),
        ]

        # Check in/out status
        last_attendance = Attendance.search([
            ('employee_id', '=', employee.id),
        ], order='check_in desc', limit=1)

        is_checked_in = last_attendance and not last_attendance.check_out

        return request.render('hr_attendance_portal.portal_my_attendance', {
            'employee':      employee,
            'attendances':   attendances,
            'pager':         pager,
            'years':         years,
            'months':        months,
            'filter_year':   filter_year or '',
            'filter_month':  filter_month or '',
            'is_checked_in': is_checked_in,
            'page_name':     'attendance',
        })

    @http.route('/my/attendance/checkin',
                type='http', auth='user', website=True, methods=['POST'])
    def portal_checkin(self, **kw):
        employee = self._get_employee_sudo()
        if not employee:
            return request.redirect('/my/attendance')

        # Check not already checked in
        Attendance = request.env['hr.attendance'].sudo()
        last = Attendance.search([
            ('employee_id', '=', employee.id),
        ], order='check_in desc', limit=1)

        if not last or last.check_out:
            Attendance.create({
                'employee_id': employee.id,
                'check_in': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            })

        return request.redirect('/my/attendance')

    @http.route('/my/attendance/checkout',
                type='http', auth='user', website=True, methods=['POST'])
    def portal_checkout(self, **kw):
        employee = self._get_employee_sudo()
        if not employee:
            return request.redirect('/my/attendance')

        Attendance = request.env['hr.attendance'].sudo()
        last = Attendance.search([
            ('employee_id', '=', employee.id),
        ], order='check_in desc', limit=1)

        if last and not last.check_out:
            last.write({
                'check_out': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            })

        return request.redirect('/my/attendance')