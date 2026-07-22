import json
from xml.parsers.expat import errors
from markupsafe import Markup
from odoo import http, _, fields
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.exceptions import AccessError, MissingError,UserError
from datetime import date
from datetime import timedelta
import logging
import bleach
import re


class RequisitionPortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if "requisition_count" in counters:
            values["requisition_count"] = (
                request.env["product.requisition"]
                .sudo()
                .search_count(self._get_requisition_domain())
            )
        return values

    def _get_requisition_domain(self):
        return [("user_id", "=", request.env.user.id)]

    def _get_products(self):
        return (
            request.env["product.product"]
            .sudo()
            .search([("type", "in", ["product", "consu"]), ("sale_ok", "=", True)])
        )

    def _get_products_json(self):
        products = self._get_products()
        return Markup(json.dumps([[p.id, p.display_name] for p in products]))
    
    def _extract_lines_from_post(self, post):
        """Rebuild a list of dicts from raw POST for template re-render."""
        restored = []
        index = 1
        while index <= 100:
            product_value = post.get(f"product_id_{index}")
            if not product_value:
                index += 1
                continue
            try:
                int(product_value)
            except Exception:
                index += 1
                continue
            restored.append({
                "index":      index,
                "product_id": product_value,
                "qty":        post.get(f"qty_{index}", "1"),
                "desc":       post.get(f"desc_{index}", ""),
                "price":      post.get(f"price_{index}", "0.00"),
            })
            index += 1
        return restored

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------
    @http.route(
        ["/my/requisitions", "/my/requisitions/page/<int:page>"],
        type="http",
        auth="user",
        website=True,
    )
    def portal_requisitions(self, page=1, sortby="date_request", **kw):
        Requisition = request.env["product.requisition"].sudo()
        domain = self._get_requisition_domain()

        sort_options = {
            "date_request": "date_request desc",
            "name": "name asc",
            "state": "state asc",
        }
        order = sort_options.get(sortby, "date_request desc")

        total = Requisition.search_count(domain)
        pager = portal_pager(
            url="/my/requisitions",
            url_args={"sortby": sortby},
            total=total,
            page=page,
            step=10,
        )
        requisitions = Requisition.search(domain, order=order, limit=10, offset=pager["offset"])

        return request.render(
            "product_requisition.portal_requisition_list",
            {
                "requisitions": requisitions,
                "page_name": "requisition",
                "pager": pager,
                "sortby": sortby,
                "default_url": "/my/requisitions",
            },
        )

    # ------------------------------------------------------------------
    # New form — GET + POST
    # ------------------------------------------------------------------
    @http.route(
        "/my/requisitions/new",
        type="http",
        auth="user",
        website=True,
        methods=["GET", "POST"],
        csrf=True,
    )
    def portal_requisition_new(self, **post):
        if request.httprequest.method == "POST":
            return self._handle_requisition_submit(post)
        
        user = request.env.user
        emp = request.env['hr.employee'].sudo().search(
            [('user_id', '=', user.id)], limit=1
        )
        
        return request.render(
            "product_requisition.portal_requisition_form",
            {
                "page_name": "requisition_new",
                "products": self._get_products(),
                "products_json": self._get_products_json(),
                "requester_name": user.partner_id.name,
                "designation": emp.job_id.name if emp and emp.job_id else "",
                "department_name" : emp.department_id.name if emp and emp.department_id else "",
                "default_department_id": emp.department_id.id if emp and emp.department_id else False,
                "today": date.today().strftime("%d/%m/%Y"),
                "errors": {},
                "values": {},
            },
        )

    def _handle_requisition_submit(self, post):
        errors = {}

        # Collect basic fields
        department_id = post.get("department_id")
        date_required = post.get("date_required") or False
        purchase_option = post.get("purchase_option", "")
        purchase_mode = post.get("purchase_mode", "local")
        priority = post.get("priority", "0")
        file_no = post.get("file_no", "").strip()[:100]
        notes = bleach.clean(post.get("notes", "").strip()[:2000], tags=[], attributes={}, strip=True)
        delivery_lead_days = post.get("delivery_lead_days", "30")
        delivery_lead_unit = post.get("delivery_lead_unit", "days")

        # Validate department
        if not department_id:
            errors["department_id"] = _("Department is required.")
        
        # Validate Required by Data
        if not date_required:
            errors['date_required'] = _("Required By date is required.")
        else:
            try:
                date_required = fields.Date.from_string(date_required)
                if date_required < date.today():
                    errors["date_required"] = _("Required By date can not be in the past.")

            except Exception:
                errors["date_required"] = _("invalid date.")

        # Validate Purchase Option
        if not purchase_option:
            errors["purchase_option"] = _("Purchase Option is required.")
        
        # Validate file no uniqueness
        if not file_no:
            errors["file_no"] = _("File / Diary Reference No. is required.")
        else:
            if not re.match(r'^[\w\s/\-\.]+$', file_no):
                errors["file_no"] = _("File Reference contains invalid characters.")
            else:
                existing_requisition = (
                    request.env['product.requisition'].sudo().search([
                    ("file_no", "=", file_no)],
                    limit = 1,
                    )
                )
                if existing_requisition:
                    errors["file_no"] = _("File / Reference No. already exists.")

        # Collect lines: product_id_1/qty_1, product_id_2/qty_2, …
        lines = []
        valid_line_count = 0  # rows that had a product selected at all
        index = 1
        while index <= 100:
            product_value = post.get(f"product_id_{index}")

            if not product_value:
                index += 1
                continue

            try:
                product_id = int(product_value)
            except Exception:
                index += 1
                continue

            # A product was selected — count it regardless of qty/price validity
            valid_line_count += 1

            try:
                qty = float(post.get(f"qty_{index}", 1))
            except Exception:
                qty = 1.0

            if qty < 0.01:
                errors[f"qty_{index}"] = _("Quantity cannot be less than 0.01 .")

            description = post.get(f"desc_{index}", "").strip()
            try:
                price = float(post.get(f"price_{index}", 0.0))
            except Exception:
                price = 0.0

            if price <= 0:
                errors[f"price_{index}"] = _("Expected Price must be greater than 0.")

            if qty > 0 and price > 0:
                lines.append((0, 0, {
                    "product_id": product_id,
                    "qty_requested": qty,
                    "description": description,
                    "estimated_unit_price": price,
                }))
            index += 1

        if valid_line_count == 0:
            errors["lines"] = [_("Please add at least one product.")]

        # ── Workflow check — before touching the ORM ────────────────────────
        if not errors.get("department_id"):
            company_id = request.env.company.id
            dept_id = int(department_id) if department_id else False
            workflow = False
            if dept_id:
                workflow = request.env['product.requisition.workflow'].sudo().search([
                    ('department_id', '=', dept_id),
                    ('active', '=', True),
                    ('company_id', '=', company_id),
                ], limit=1)
            if not workflow:
                workflow = request.env['product.requisition.workflow'].sudo().search([
                    ('department_id', '=', False),
                    ('active', '=', True),
                    ('company_id', '=', company_id),
                ], limit=1)
            if not workflow:
                dept = request.env['hr.department'].sudo().browse(dept_id) if dept_id else None
                dept_name = dept.name if dept else _('Unknown')
                errors['submit'] = _(
                    "No approval workflow is configured for department '%s'. "
                    "Please ask your administrator to set up a workflow under: "
                    "Product Requisitions → Configuration → Approval Workflows."
                ) % dept_name
            # Validate department
            if not department_id:
                user = request.env.user
                emp = request.env['hr.employee'].sudo().search(
                    [('user_id', '=', user.id)], limit=1
                )
                if not emp:
                    errors['submit'] = _(
                        "No employee record is linked to your account. "
                        "Please contact your administrator to set up your employee profile."
                    )
                elif not emp.department_id:
                    errors['submit'] = _(
                        "Your employee profile has no department assigned. "
                        "Please contact your administrator to assign you to a department."
                    )
                else:
                    errors['submit'] = _("Department is required.")
            # ── Re-render form if any validation errors ──────────────────────────
        if errors:
            user = request.env.user
            emp = request.env['hr.employee'].sudo().search(
                [('user_id', '=', user.id)], limit=1
            )
            return request.render(
                "product_requisition.portal_requisition_form",
                {
                    "page_name": "requisition_new",
                    "products": self._get_products(),
                    "products_json": self._get_products_json(),
                    "department_name" : emp.department_id.name if emp and emp.department_id else "",
                    "default_department_id": emp.department_id.id if emp and emp.department_id else False,
                    "requester_name": user.partner_id.name,
                    "designation": emp.job_id.name if emp and emp.job_id else "",
                    "today": date.today().strftime("%d/%m/%Y"),
                    "errors": errors,
                    "values": post,
                    "restored_lines": self._extract_lines_from_post(post),  # ← ADD THIS
                },
            )
        # Prepare delivery lead time in days

        try:
            requisition = (
                request.env["product.requisition"]
                .sudo()
                .create(
                    {
                        "partner_id": request.env.user.partner_id.id,
                        "user_id": request.env.user.id,
                        "department_id": int(department_id) if department_id else False,
                        "date_required": date_required or False,
                        "purchase_option": purchase_option or False,
                        "purchase_mode": purchase_mode,
                        "priority": str(priority) if priority else "0",
                        "file_no": file_no,
                        "delivery_lead_days": int(delivery_lead_days) if delivery_lead_days else 30,
                        "delivery_lead_unit": delivery_lead_unit,
                        "notes": notes,
                        "requisition_line_ids": lines,
                        "state": "submitted",
                    }
                )
            )
            try:
                requisition.action_submit()
            except Exception:
                _logger.exception(
                    "Could not auto-start approval workflow for %s",
                    requisition.name,
                )


            # ─────────────────────────────────────────────────────────────

            return request.redirect(f"/my/requisitions/{requisition.id}")
        except Exception as e:
            # Log error and show it on form
            _logger = logging.getLogger(__name__)
            _logger.exception("Error creating requisition")
            errors["submit"] = f"Error creating requisition: {str(e)}"
            user = request.env.user
            emp = request.env['hr.employee'].sudo().search(
                [('user_id', '=', user.id)], limit=1
            )
            return request.render(
                "product_requisition.portal_requisition_form",
                {
                    "page_name": "requisition_new",
                    "products": self._get_products(),
                    "products_json": self._get_products_json(),
                    "requester_name": user.partner_id.name,
                    "designation": emp.job_id.name if emp and emp.job_id else "",
                    "department_name" : emp.department_id.name if emp and emp.department_id else "",
                    "default_department_id": emp.department_id.id if emp and emp.department_id else False,
                    "today": date.today().strftime("%d/%m/%Y"),
                    "errors": errors,
                    "values": post,
                    "restored_lines": self._extract_lines_from_post(post),  # ← ADD THIS
                },
            )
    # ------------------------------------------------------------------
    # Detail view
    # ------------------------------------------------------------------
    @http.route(
        "/my/requisitions/<int:requisition_id>",
        type="http",
        auth="user",
        website=True,
    )
    def portal_requisition_detail(self, requisition_id, **kw):
        requisition = request.env["product.requisition"].sudo().browse(requisition_id)
        if not requisition.exists() or requisition.user_id.id != request.env.user.id:
            return request.redirect("/my/requisitions")

        user = request.env.user
        emp = request.env['hr.employee'].sudo().search(
            [('user_id', '=', user.id)], limit=1
        )

        return request.render(
            "product_requisition.portal_requisition_detail",
            {
                "requisition": requisition,
                "page_name":   "requisition_detail",
            },
)
