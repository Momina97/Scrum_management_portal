from odoo import http
from odoo.http import request
from odoo.addons.hr_payroll_portal.controllers.portal import PayrollPortal
from datetime import date
import calendar


class PayrollDashboardPortal(PayrollPortal):

    def _get_payslip_stats(self, employee, domain=None):
        Payslip = request.env['hr.payslip'].sudo()
        if domain is None:
            domain = [
                ('employee_id', '=', employee.id),
                ('state', 'in', ['done', 'paid']),
            ]

        all_payslips = Payslip.search(domain, order='date_from desc')
        today = date.today()

        total_gross = sum(p.gross_wage or 0 for p in all_payslips)
        total_net = sum(p.net_wage or 0 for p in all_payslips)
        total_deductions = total_gross - total_net

        recent_payslips = all_payslips[:5]

        # Monthly net pay — last 6 months
        monthly_data = []
        for offset in range(5, -1, -1):
            month_num = today.month - offset
            year_num = today.year
            while month_num <= 0:
                month_num += 12
                year_num -= 1
            m, y = month_num, year_num
            month_slips = all_payslips.filtered(
                lambda p, m=m, y=y: p.date_from and p.date_from.month == m and p.date_from.year == y
            )
            net = sum(p.net_wage or 0 for p in month_slips)
            monthly_data.append({
                'label': '%s %s' % (calendar.month_abbr[m], str(y)[2:]),
                'value': round(net, 2),
                'value_str': '%.0f' % net,
            })

        max_monthly = max((i['value'] for i in monthly_data), default=1) or 1
        monthly_counts = []
        for item in monthly_data:
            percent = int(round((item['value'] / max_monthly) * 100))
            monthly_counts.append({
                'label': item['label'],
                'value': item['value'],
                'value_str': item['value_str'],
                'percent': percent,
                'style': 'height: %s%%' % percent,
            })

        # Yearly comparison — last 3 years
        all_years_slips = Payslip.search([
            ('employee_id', '=', employee.id),
            ('state', 'in', ['done', 'paid']),
        ])
        years_set = sorted(set(
            p.date_from.year for p in all_years_slips if p.date_from
        ), reverse=True)[:3]

        yearly_data = []
        for y in reversed(years_set):
            year_slips = all_years_slips.filtered(
                lambda p, y=y: p.date_from and p.date_from.year == y
            )
            gross = sum(p.gross_wage or 0 for p in year_slips)
            net = sum(p.net_wage or 0 for p in year_slips)
            yearly_data.append({
                'year': str(y),
                'gross': round(gross, 2),
                'net': round(net, 2),
                'gross_str': '%.0f' % gross,
                'net_str': '%.0f' % net,
            })

        max_yearly = max((i['gross'] for i in yearly_data), default=1) or 1
        for item in yearly_data:
            item['gross_pct'] = 'width: %s%%' % int(round(item['gross'] / max_yearly * 100))
            item['net_pct'] = 'width: %s%%' % int(round(item['net'] / max_yearly * 100))

        # Earnings vs deductions breakdown
        total = total_gross or 1
        breakdown = [
            {
                'label': 'Net Pay',
                'value': round(total_net, 2),
                'value_str': '%.0f' % total_net,
                'style': 'width: %s%%' % int(round(total_net / total * 100)),
                'class': 'cp_ot_approved',
                'percent': int(round(total_net / total * 100)),
            },
            {
                'label': 'Deductions',
                'value': round(total_deductions, 2),
                'value_str': '%.0f' % total_deductions,
                'style': 'width: %s%%' % int(round(total_deductions / total * 100)),
                'class': 'cp_ot_refused',
                'percent': int(round(total_deductions / total * 100)),
            },
        ]

        return {
            'total_payslips': len(all_payslips),
            'total_gross': round(total_gross, 2),
            'total_net': round(total_net, 2),
            'total_deductions': round(total_deductions, 2),
            'recent_payslips': recent_payslips,
            'monthly_counts': monthly_counts,
            'yearly_data': yearly_data,
            'breakdown': breakdown,
        }

    @http.route(['/my/payslips', '/my/payslips/dashboard'],
                type='http',
                auth='user',
                website=True)
    def portal_payslip_dashboard(self, filter_year=None, filter_month=None, **kw):
        employee = self._get_employee_sudo()
        if not employee:
            return request.render('hr_payroll_portal.portal_no_employee', {})

        today = date.today()
        base_domain = [
            ('employee_id', '=', employee.id),
            ('state', 'in', ['done', 'paid']),
        ]

        if filter_year and filter_month:
            year, month = int(filter_year), int(filter_month)
            last_day = calendar.monthrange(year, month)[1]
            base_domain += [
                ('date_from', '>=', '%s-%s-01' % (year, str(month).zfill(2))),
                ('date_to', '<=', '%s-%s-%s' % (year, str(month).zfill(2), last_day)),
            ]
        elif filter_year:
            base_domain += [
                ('date_from', '>=', '%s-01-01' % filter_year),
                ('date_to', '<=', '%s-12-31' % filter_year),
            ]
        elif filter_month:
            month = int(filter_month)
            base_domain += [
                ('date_from', '>=', '%s-%s-01' % (today.year, str(month).zfill(2))),
                ('date_from', '<=', '%s-%s-%s' % (
                    today.year, str(month).zfill(2),
                    calendar.monthrange(today.year, month)[1]
                )),
            ]

        # Build year list
        Payslip = request.env['hr.payslip'].sudo()
        all_slips = Payslip.search([
            ('employee_id', '=', employee.id),
            ('state', 'in', ['done', 'paid']),
        ])
        years = sorted(set(
            p.date_from.year for p in all_slips if p.date_from
        ), reverse=True) or [today.year]

        months = [
            ('1', 'January'), ('2', 'February'), ('3', 'March'),
            ('4', 'April'), ('5', 'May'), ('6', 'June'),
            ('7', 'July'), ('8', 'August'), ('9', 'September'),
            ('10', 'October'), ('11', 'November'), ('12', 'December'),
        ]

        stats = self._get_payslip_stats(employee, base_domain)

        return request.render('hr_payroll_portal.portal_payslip_dashboard', {
            'employee':         employee,
            'total_payslips':   stats['total_payslips'],
            'total_gross':      stats['total_gross'],
            'total_net':        stats['total_net'],
            'total_deductions': stats['total_deductions'],
            'recent_payslips':  stats['recent_payslips'],
            'monthly_counts':   stats['monthly_counts'],
            'yearly_data':      stats['yearly_data'],
            'breakdown':        stats['breakdown'],
            'years':            years,
            'months':           months,
            'filter_year':      filter_year or '',
            'filter_month':     filter_month or '',
            'page_name':        'payslip_dashboard',
        })