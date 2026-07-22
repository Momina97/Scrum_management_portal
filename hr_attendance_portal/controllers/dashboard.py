from odoo import http, _
from odoo.http import request
from .portal import AttendancePortal
from datetime import date, datetime
import calendar, pytz


class AttendanceDashboardPortal(AttendancePortal):

    @http.route(['/my/attendance', '/my/attendance/dashboard'],
                type='http',
                auth='user',
                website=True
                )
    def portal_attendance_dashboard(self, **kw):
        filter_year = kw.get('filter_year')
        filter_month = kw.get('filter_month')
        error = kw.get('error') or request.params.get('error')
        if error is not None:
            error = str(error)

        employee = self._get_employee_sudo()
        if not employee:
            return request.render('hr_attendance_portal.portal_no_employee', {})

        today = date.today()

        # Build domain based on filters
        base_domain = [('employee_id', '=', employee.id)]
        if filter_year and filter_month:
            year, month = int(filter_year), int(filter_month)
            last_day = calendar.monthrange(year, month)[1]
            base_domain += [
                ('check_in', '>=', '%s-%s-01 00:00:00' % (year, str(month).zfill(2))),
                ('check_in', '<=', '%s-%s-%s 23:59:59' % (year, str(month).zfill(2), last_day)),
            ]
        elif filter_year:
            base_domain += [
                ('check_in', '>=', '%s-01-01 00:00:00' % filter_year),
                ('check_in', '<=', '%s-12-31 23:59:59' % filter_year),
            ]
        elif filter_month:
            month = int(filter_month)
            base_domain += [
                ('check_in', '>=', '%s-%s-01 00:00:00' % (today.year, str(month).zfill(2))),
                ('check_in', '<=', '%s-%s-%s 23:59:59' % (
                    today.year, str(month).zfill(2),
                    calendar.monthrange(today.year, month)[1]
                )),
            ]

        # Build year list
        Attendance = request.env['hr.attendance'].sudo()
        all_years_recs = Attendance.search([('employee_id', '=', employee.id)])
        years = sorted(set(
            a.check_in.year for a in all_years_recs if a.check_in
        ), reverse=True) or [today.year]

        months = [
            ('1', 'January'), ('2', 'February'), ('3', 'March'),
            ('4', 'April'), ('5', 'May'), ('6', 'June'),
            ('7', 'July'), ('8', 'August'), ('9', 'September'),
            ('10', 'October'), ('11', 'November'), ('12', 'December'),
        ]

        stats = self._get_attendance_stats(employee, base_domain)

        user_tz = request.env.user.tz or 'UTC'
        tz = pytz.timezone(user_tz)

        today_timeline = []
        for att in stats['today_attendances']:
            if att.check_in:
                local_checkin = pytz.utc.localize(att.check_in).astimezone(tz)
                check_in_hour = local_checkin.hour + local_checkin.minute / 60

                if att.check_out:
                    local_checkout = pytz.utc.localize(att.check_out).astimezone(tz)
                    check_out_hour = local_checkout.hour + local_checkout.minute / 60
                    is_active = False
                    end_hour = check_out_hour
                    check_out_str = local_checkout.strftime('%H:%M')
                else:
                    check_out_hour = None
                    is_active = True
                    now_local = datetime.now(tz)
                    end_hour = now_local.hour + now_local.minute / 60
                    check_out_str = now_local.strftime('%H:%M')

                left_pct = check_in_hour / 24 * 100
                width_pct = (end_hour - check_in_hour) / 24 * 100

                today_timeline.append({
                    'check_in_hour': check_in_hour,
                    'check_out_hour': check_out_hour,
                    'is_active': is_active,
                    'check_in_str': local_checkin.strftime('%H:%M'),
                    'check_out_str': check_out_str,
                    'left_pct': '%.4f%%' % left_pct,
                    'width_pct': '%.4f%%' % width_pct,
                })


        return request.render('hr_attendance_portal.portal_attendance_dashboard', {
            'employee':          employee,
            'total_records':     stats['total_records'],
            'total_worked':      stats['total_worked'],
            'approved_count':    stats['approved_count'],
            'pending_count':    stats['pending_count'],
            'refused_count':     stats['refused_count'],
            'today_records':     stats['today_records'],
            'recent_records':    stats['recent_records'],
            'monthly_counts':    stats['monthly_counts'],
            'weekly_data':       stats['weekly_data'],
            'overtime_breakdown': stats['overtime_breakdown'],
            'years':             years,
            'months':            months,
            'filter_year':       filter_year or '',
            'filter_month':      filter_month or '',
            'page_name':         'attendance_dashboard',
            'today_timeline': today_timeline,
            'error':            error,
        })
