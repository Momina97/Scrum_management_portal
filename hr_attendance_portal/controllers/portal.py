from odoo import http, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.exceptions import AccessError
from datetime import date, datetime, timedelta
import calendar, pytz


class AttendancePortal(CustomerPortal):
    _SORTABLE_FIELDS = {
        'check_in': 'check_in',
        'worked_hours': 'worked_hours',
        'overtime_hours': 'overtime_hours',
    }

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

    def _get_attendance_stats(self, employee, domain=None):
        Attendance = request.env['hr.attendance'].sudo()
        if domain is None:
            domain = [('employee_id', '=', employee.id)]

        all_attendances = Attendance.search(domain, order='check_in desc')
        today = date.today()

        # Get user timezone
        user_tz = request.env.user.tz or 'UTC'
        tz = pytz.timezone(user_tz)

        def to_local_date(dt):
            """Convert UTC datetime to local date string"""
            if not dt:
                return None
            if dt.tzinfo is None:
                dt = pytz.utc.localize(dt)
            return dt.astimezone(tz).strftime('%Y-%m-%d')

        def to_local_month_year(dt):
            """Return (year, month) in local timezone"""
            if not dt:
                return None, None
            if dt.tzinfo is None:
                dt = pytz.utc.localize(dt)
            local_dt = dt.astimezone(tz)
            return local_dt.year, local_dt.month

        total_worked = sum(att.worked_hours or 0 for att in all_attendances)
        total_worked_str = '%02d:%02d' % (int(total_worked), int((total_worked % 1) * 60))

        approved_count = len(all_attendances.filtered(
            lambda a: a.overtime_hours and a.overtime_status == 'approved'
        ))
        pending_count = len(all_attendances.filtered(
            lambda a: a.overtime_hours and a.overtime_status == 'to_approve'
        ))
        refused_count = len(all_attendances.filtered(
            lambda a: a.overtime_hours and a.overtime_status == 'refused'
        ))

        today_str = today.strftime('%Y-%m-%d')
        today_records = all_attendances.filtered(
            lambda a: to_local_date(a.check_in) == today_str
        )
        recent_records = all_attendances[:5]

        # Monthly chart — last 6 months oldest to newest
        monthly_data = []
        for offset in range(5, -1, -1):
            month_num = today.month - offset
            year_num = today.year
            while month_num <= 0:
                month_num += 12
                year_num -= 1
            m, y = month_num, year_num
            month_records = all_attendances.filtered(
                lambda a, m=m, y=y: to_local_month_year(a.check_in) == (y, m)
            )
            monthly_data.append({
                'label': '%s %s' % (calendar.month_abbr[m], str(y)[2:]),
                'value': len(month_records),
            })

        max_monthly = max((i['value'] for i in monthly_data), default=1) or 1
        monthly_counts = []
        for item in monthly_data:
            percent = int(round((item['value'] / max_monthly) * 100))
            monthly_counts.append({
                'label': item['label'],
                'value': item['value'],
                'percent': percent,
                'style': 'height: %s%%' % percent,
            })

        # Weekly hours — Mon to Sun of current week in local timezone
        week_start = today - timedelta(days=today.weekday())
        weekly_data = []
        day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        for i in range(7):
            day = week_start + timedelta(days=i)
            day_str = day.strftime('%Y-%m-%d')
            day_records = all_attendances.filtered(
                lambda a, d=day_str: to_local_date(a.check_in) == d
            )
            hours = sum(a.worked_hours or 0 for a in day_records)  # keep full precision
            weekly_data.append({
                'label': day_names[i],
                'value': hours,  # don't round here
                'is_today': day == today,
                'hours_str': '%02d:%02d' % (int(hours), round((hours % 1) * 60)),  # round minutes only
            })

        max_weekly = max((i['value'] for i in weekly_data), default=1) or 1
        for item in weekly_data:
            percent = int(round((item['value'] / max_weekly) * 100))
            item['percent'] = percent
            item['style'] = 'height: %s%%' % percent

        # Overtime breakdown
        total_overtime = approved_count + pending_count + refused_count or 1
        overtime_breakdown = [
            {
                'label': 'Approved',
                'count': approved_count,
                'percent': int(round(approved_count / total_overtime * 100)),
                'class': 'ca_ot_approved',
                'style': 'width: %s%%' % int(round(approved_count / total_overtime * 100)),
            },
            {
                'label': 'Pending',
                'count': pending_count,
                'percent': int(round(pending_count / total_overtime * 100)),
                'class': 'ca_ot_pending',
                'style': 'width: %s%%' % int(round(pending_count / total_overtime * 100)),
            },
            {
                'label': 'Refused',
                'count': refused_count,
                'percent': int(round(refused_count / total_overtime * 100)),
                'class': 'ca_ot_refused',
                'style': 'width: %s%%' % int(round(refused_count / total_overtime * 100)),
            },
        ]

        return {
            'total_records': len(all_attendances),
            'total_worked': total_worked_str,
            'approved_count': approved_count,
            'pending_count': pending_count,
            'refused_count': refused_count,
            'today_records': len(today_records),
            'recent_records': recent_records,
            'monthly_counts': monthly_counts,
            'weekly_data': weekly_data,
            'overtime_breakdown': overtime_breakdown,
            'today_attendances': today_records,
        }

    @http.route(['/my/attendance/list', '/my/attendance/list/page/<int:page>', '/my/attendance/page/<int:page>'],
                type='http',
                auth='user',
                website=True
                )
    def portal_my_attendance(self, page=1, filter_year=None, filter_month=None,
                              sort_field=None, sort_order=None, error=None, **kw):
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

        # ---- Build sort order ----
        if sort_field not in self._SORTABLE_FIELDS:
            sort_field = 'check_in'
        sort_order = 'asc' if sort_order == 'asc' else 'desc'

        order_field = self._SORTABLE_FIELDS[sort_field]
        if order_field == 'check_in':
            order_str = 'check_in %s' % sort_order
        else:
            order_str = '%s %s, check_in desc' % (order_field, sort_order)

        attendance_count = Attendance.search_count(domain)
        pager = portal_pager(
            url='/my/attendance/list',
            url_args={
                'filter_year': filter_year or '',
                'filter_month': filter_month or '',
                'sort_field': sort_field,
                'sort_order': sort_order,
            },
            total=attendance_count,
            page=page,
            step=20,
        )
        attendances = Attendance.search(
            domain,
            order=order_str,
            limit=20,
            offset=pager['offset'],
        )

        months = [
            ('1', 'January'), ('2', 'February'), ('3', 'March'),
            ('4', 'April'), ('5', 'May'), ('6', 'June'),
            ('7', 'July'), ('8', 'August'), ('9', 'September'),
            ('10', 'October'), ('11', 'November'), ('12', 'December'),
        ]

        # All records for stats (no pager limit)
        all_attendances = Attendance.search(domain, order='check_in desc')

        stats = self._get_attendance_stats(employee, domain)

        return request.render('hr_attendance_portal.portal_my_attendance', {
            'employee':         employee,
            'attendances':      attendances,       # paginated — for the table
            'all_attendances':  all_attendances,   # full — for stats
            'total_records':    attendance_count,
            'total_worked':     stats['total_worked'],
            'approved_count':   stats['approved_count'],
            'pending_count':    stats['pending_count'],
            'pager':            pager,
            'years':            years,
            'months':           months,
            'filter_year':      filter_year or '',
            'filter_month':     filter_month or '',
            'sort_field':       sort_field,
            'sort_order':       sort_order,
            'error':            error,
            'page_name':        'attendance_list',
        })

    @http.route('/my/attendance/checkin',
                type='http', auth='user', website=True, methods=['POST'])
    def portal_checkin(self, **kw):
        employee = self._get_employee_sudo()
        if not employee:
            return request.redirect('/my/attendance')
        
        if hasattr(employee, 'allow_odoo_attendance') and not employee.allow_odoo_attendance:
            return request.redirect('/my/attendance?error=biometric')

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
        
        if hasattr(employee, 'allow_odoo_attendance') and not employee.allow_odoo_attendance:
            return request.redirect('/my/attendance?error=biometric')

        Attendance = request.env['hr.attendance'].sudo()
        last = Attendance.search([
            ('employee_id', '=', employee.id),
        ], order='check_in desc', limit=1)

        if last and not last.check_out:
            last.write({
                'check_out': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            })

        return request.redirect('/my/attendance')