from odoo import http, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.exceptions import AccessError
from datetime import date
from dateutil.relativedelta import relativedelta
import calendar


class PayrollPortal(CustomerPortal):

    def _get_employee_sudo(self):
        return request.env['hr.employee'].sudo().search(
            [('user_id', '=', request.env.user.id)],
            limit=1,
        )

    def _get_payslip_sudo(self, payslip_id, employee):
        payslip = request.env['hr.payslip'].sudo().browse(payslip_id)
        if not payslip.exists() or payslip.employee_id.id != employee.id:
            raise AccessError(_("You do not have access to this payslip."))
        return payslip

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'payslip_count' in counters:
            employee = self._get_employee_sudo()
            if employee:
                values['payslip_count'] = request.env['hr.payslip'].sudo().search_count([
                    ('employee_id', '=', employee.id),
                    ('state', 'in', ['done', 'paid']),
                ])
            else:
                values['payslip_count'] = 0
        return values

    @http.route(['/my/payslips/list', '/my/payslips/list/page/<int:page>'],
                type='http',
                auth='user',
                website=True)
    def portal_my_payslips(self, page=1, filter_year=None, filter_month=None, **kw):
        page = int(page)
        employee = self._get_employee_sudo()

        if not employee:
            return request.render('hr_payroll_portal.portal_no_employee', {})

        today = date.today()

        # Default: last 6 months
        if not filter_year and not filter_month:
            six_months_ago = today.replace(day=1) - relativedelta(months=6)
            date_domain = [
                ('date_from', '>=', six_months_ago.strftime('%Y-%m-%d')),
            ]
        else:
            date_domain = []
            if filter_year:
                date_domain += [
                    ('date_from', '>=', '%s-01-01' % filter_year),
                    ('date_to', '<=', '%s-12-31' % filter_year),
                ]
            if filter_month:
                year = int(filter_year or today.year)
                month = int(filter_month)
                last_day = calendar.monthrange(year, month)[1]
                date_domain += [
                    ('date_from', '>=', '%s-%s-01' % (year, str(month).zfill(2))),
                    ('date_from', '<=', '%s-%s-%s' % (year, str(month).zfill(2), last_day)),
                ]

        domain = [
            ('employee_id', '=', employee.id),
            ('state', 'in', ['done', 'paid']),
        ] + date_domain

        Payslip = request.env['hr.payslip'].sudo()
        payslip_count = Payslip.search_count(domain)
        pager = portal_pager(
            url='/my/payslips/list',
            url_args={
                'filter_year': filter_year or '',
                'filter_month': filter_month or '',
            },
            total=payslip_count,
            page=page,
            step=10,
        )
        payslips = Payslip.search(
            domain,
            order='date_to desc',
            limit=10,
            offset=pager['offset'],
        )

        # Build year list
        all_payslips = Payslip.search([
            ('employee_id', '=', employee.id),
            ('state', 'in', ['done', 'paid']),
        ])
        years = sorted(set(
            p.date_from.year for p in all_payslips if p.date_from
        ), reverse=True)

        months = [
            ('1', 'January'), ('2', 'February'), ('3', 'March'),
            ('4', 'April'), ('5', 'May'), ('6', 'June'),
            ('7', 'July'), ('8', 'August'), ('9', 'September'),
            ('10', 'October'), ('11', 'November'), ('12', 'December'),
        ]

        return request.render('hr_payroll_portal.portal_my_payslips', {
            'employee':     employee,
            'payslips':     payslips,
            'pager':        pager,
            'years':        years,
            'months':       months,
            'filter_year':  filter_year or '',
            'filter_month': filter_month or '',
            'page_name':    'payslips',
        })

    @http.route('/my/payslips/<int:payslip_id>',
                type='http',
                auth='user',
                website=True)
    def portal_payslip_detail(self, payslip_id, **kw):
        employee = self._get_employee_sudo()

        if not employee:
            return request.render('hr_payroll_portal.portal_no_employee', {})

        try:
            payslip = self._get_payslip_sudo(payslip_id, employee)
        except AccessError:
            return request.render('website.403')

        earnings = payslip.line_ids.filtered(
            lambda l: l.category_id.code in ('BASIC', 'ALW', 'GROSS')
            and l.appears_on_payslip
        )
        deductions = payslip.line_ids.filtered(
            lambda l: l.category_id.code in ('DED', 'COMP')
            and l.appears_on_payslip
        )
        net_line = payslip.line_ids.filtered(
            lambda l: l.category_id.code == 'NET'
            and l.appears_on_payslip
        )

        return request.render('hr_payroll_portal.portal_payslip_detail', {
            'employee':   employee,
            'payslip':    payslip,
            'earnings':   earnings,
            'net_line':   net_line,
            'page_name':  'payslip_detail',
        })

    @http.route('/my/payslips/<int:payslip_id>/download',
                type='http', auth='user', website=True)
    def portal_payslip_download(self, payslip_id, **kw):
        employee = self._get_employee_sudo()

        if not employee:
            return request.redirect('/my/payslips')

        try:
            payslip = self._get_payslip_sudo(payslip_id, employee)
        except AccessError:
            return request.redirect('/my/payslips')

        return request.make_response(
            request.env['ir.actions.report'].sudo()._render_qweb_pdf(
                'hr_payroll.action_report_payslip', payslip.ids
            )[0],
            headers=[
                ('Content-Type', 'application/pdf'),
                ('Content-Disposition',
                 'attachment; filename="Payslip-%s.pdf"' % payslip.name),
            ]
        )