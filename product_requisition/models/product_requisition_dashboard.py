import json
import calendar
import logging
from datetime import date
from odoo import models, fields, api

_logger = logging.getLogger(__name__)

_STATE_LABELS = {
    "draft": "Draft", "submitted": "Submitted", "in_approval": "In Approval",
    "approved": "Approved", "rejected": "Rejected", "cancelled": "Cancelled",
    "rfq_created": "RFQ Created", "done": "Done",
}


class ProductRequisitionDashboard(models.Model):
    """Singleton dashboard — all fields are non-stored computed, auto-fresh on every load."""
    _name = "product.requisition.dashboard"
    _description = "Product Requisition Dashboard"

    name = fields.Char(default="Product Requisition Dashboard")

    # KPI Counters
    total_count         = fields.Integer(compute="_compute_kpi", store=False)
    draft_count         = fields.Integer(compute="_compute_kpi", store=False)
    submitted_count     = fields.Integer(compute="_compute_kpi", store=False)
    in_approval_count   = fields.Integer(compute="_compute_kpi", store=False)
    approved_count      = fields.Integer(compute="_compute_kpi", store=False)
    rejected_count      = fields.Integer(compute="_compute_kpi", store=False)
    cancelled_count     = fields.Integer(compute="_compute_kpi", store=False)
    rfq_created_count   = fields.Integer(compute="_compute_kpi", store=False)
    done_count          = fields.Integer(compute="_compute_kpi", store=False)
    pending_my_approval = fields.Integer(compute="_compute_kpi", store=False)

    # Financial
    total_estimated_cost    = fields.Float(compute="_compute_kpi", digits="Product Price", store=False)
    approved_estimated_cost = fields.Float(compute="_compute_kpi", digits="Product Price", store=False)
    this_month_count        = fields.Integer(compute="_compute_kpi", store=False)
    this_month_approved     = fields.Integer(compute="_compute_kpi", store=False)
    this_month_rejected     = fields.Integer(compute="_compute_kpi", store=False)

    # Chart JSON
    status_chart_data  = fields.Text(compute="_compute_charts", store=False)
    monthly_chart_data = fields.Text(compute="_compute_charts", store=False)

    # Table JSON
    department_table_data = fields.Text(compute="_compute_tables", store=False)
    type_table_data       = fields.Text(compute="_compute_tables", store=False)
    recent_table_data     = fields.Text(compute="_compute_tables", store=False)

    @api.depends()
    def _compute_kpi(self):
        Req = self.env["product.requisition"]
        today = date.today()
        month_start = today.replace(day=1)

        def count(domain):
            return Req.search_count(domain)

        total       = count([])
        draft       = count([("state", "=", "draft")])
        submitted   = count([("state", "=", "submitted")])
        in_approval = count([("state", "=", "in_approval")])
        approved    = count([("state", "=", "approved")])
        rejected    = count([("state", "=", "rejected")])
        cancelled   = count([("state", "=", "cancelled")])
        rfq_created = count([("state", "=", "rfq_created")])
        done        = count([("state", "=", "done")])

        all_recs      = Req.search([])
        total_cost    = sum(all_recs.mapped("estimated_cost"))
        approved_recs = Req.search([("state", "in", ("approved", "rfq_created", "done"))])
        approved_cost = sum(approved_recs.mapped("estimated_cost"))

        this_month      = count([("date_request", ">=", month_start)])
        this_month_appr = count([("date_request", ">=", month_start), ("state", "in", ("approved", "rfq_created", "done"))])
        this_month_rej  = count([("date_request", ">=", month_start), ("state", "=", "rejected")])

        pending_mine = count([
            ("state", "=", "in_approval"),
            ("current_approver_id", "=", self.env.uid),
        ])

        for rec in self:
            rec.total_count           = total
            rec.draft_count           = draft
            rec.submitted_count       = submitted
            rec.in_approval_count     = in_approval
            rec.approved_count        = approved
            rec.rejected_count        = rejected
            rec.cancelled_count       = cancelled
            rec.rfq_created_count     = rfq_created
            rec.done_count            = done
            rec.total_estimated_cost  = total_cost
            rec.approved_estimated_cost = approved_cost
            rec.this_month_count      = this_month
            rec.this_month_approved   = this_month_appr
            rec.this_month_rejected   = this_month_rej
            rec.pending_my_approval   = pending_mine

    @api.depends()
    def _compute_charts(self):
        Req   = self.env["product.requisition"]
        today = date.today()

        def count(domain):
            return Req.search_count(domain)

        state_chart_cfg = [
            ("Draft",       count([("state", "=", "draft")]),       "#94a3b8"),
            ("Submitted",   count([("state", "=", "submitted")]),   "#60a5fa"),
            ("In Approval", count([("state", "=", "in_approval")]), "#f59e0b"),
            ("Approved",    count([("state", "=", "approved")]),    "#10b981"),
            ("Rejected",    count([("state", "=", "rejected")]),    "#ef4444"),
            ("Cancelled",   count([("state", "=", "cancelled")]),   "#6b7280"),
            ("RFQ Created", count([("state", "=", "rfq_created")]), "#8b5cf6"),
            ("Done",        count([("state", "=", "done")]),        "#3b82f6"),
        ]
        status_json = json.dumps({
            "labels": [s[0] for s in state_chart_cfg],
            "values": [s[1] for s in state_chart_cfg],
            "colors": [s[2] for s in state_chart_cfg],
        })

        labels, counts, approved_m, rejected_m = [], [], [], []
        for i in range(5, -1, -1):
            yr, mn = today.year, today.month - i
            while mn <= 0:
                mn += 12
                yr -= 1
            m_start = date(yr, mn, 1)
            m_end   = date(yr, mn, calendar.monthrange(yr, mn)[1])
            dom = [("date_request", ">=", m_start), ("date_request", "<=", m_end)]
            labels.append(m_start.strftime("%b %Y"))
            counts.append(count(dom))
            approved_m.append(count(dom + [("state", "in", ("approved", "rfq_created", "done"))]))
            rejected_m.append(count(dom + [("state", "=", "rejected")]))

        monthly_json = json.dumps({
            "labels":   labels,
            "counts":   counts,
            "approved": approved_m,
            "rejected": rejected_m,
        })

        for rec in self:
            rec.status_chart_data  = status_json
            rec.monthly_chart_data = monthly_json

    @api.depends()
    def _compute_tables(self):
        Req = self.env["product.requisition"]

        def count(domain):
            return Req.search_count(domain)

        total = count([])

        dept_data = Req.read_group([], ["department_id"], ["department_id"])
        dept_rows = []
        for row in dept_data:
            dept_id   = row["department_id"][0] if row["department_id"] else False
            dept_name = row["department_id"][1] if row["department_id"] else "No Department"
            t = row["department_id_count"]
            dept_rows.append({
                "name":     dept_name,
                "total":    t,
                "approved": count([("department_id", "=", dept_id), ("state", "in", ("approved", "rfq_created", "done"))]),
                "pending":  count([("department_id", "=", dept_id), ("state", "in", ("submitted", "in_approval"))]),
                "perc":     round(t / total * 100, 1) if total else 0,
            })

        type_data = Req.read_group([], ["purchase_type"], ["purchase_type"])
        type_rows = []
        type_label_map = {"goods": "Goods", "service": "Service"}
        for row in type_data:
            ptype = row["purchase_type"]
            t = row["purchase_type_count"]
            type_rows.append({
                "label": type_label_map.get(ptype, ptype or "N/A"),
                "total": t,
                "perc":  round(t / total * 100, 1) if total else 0,
            })

        recent_recs = Req.search([], order="date_request desc, id desc", limit=10)
        recent_rows = []
        for rec in recent_recs:
            recent_rows.append({
                "id":        rec.id,
                "ref":       rec.name,
                "user":      rec.user_id.name or "",
                "dept":      rec.department_id.name or "—",
                "date":      rec.date_request.isoformat() if rec.date_request else "",
                "state":     _STATE_LABELS.get(rec.state, rec.state),
                "state_key": rec.state,
                "cost":      rec.estimated_cost,
            })

        for rec in self:
            rec.department_table_data = json.dumps(dept_rows)
            rec.type_table_data       = json.dumps(type_rows)
            rec.recent_table_data     = json.dumps(recent_rows)

    # -- Window Actions ------------------------------------------------------
    def action_open_dashboard(self):
        return {"type": "ir.actions.act_window", "name": "Requisition Dashboard",
                "res_model": "product.requisition.dashboard", "res_id": self.id,
                "view_mode": "form", "target": "current"}

    def action_open_all(self):
        return {"type": "ir.actions.act_window", "name": "All Requisitions",
                "res_model": "product.requisition", "view_mode": "list,form"}

    def action_open_draft(self):
        return {"type": "ir.actions.act_window", "name": "Draft",
                "res_model": "product.requisition", "view_mode": "list,form",
                "domain": [("state", "=", "draft")]}

    def action_open_submitted(self):
        return {"type": "ir.actions.act_window", "name": "Submitted",
                "res_model": "product.requisition", "view_mode": "list,form",
                "domain": [("state", "=", "submitted")]}

    def action_open_in_approval(self):
        return {"type": "ir.actions.act_window", "name": "In Approval",
                "res_model": "product.requisition", "view_mode": "list,form",
                "domain": [("state", "=", "in_approval")]}

    def action_open_approved(self):
        return {"type": "ir.actions.act_window", "name": "Approved",
                "res_model": "product.requisition", "view_mode": "list,form",
                "domain": [("state", "in", ("approved", "rfq_created", "done"))]}

    def action_open_rejected(self):
        return {"type": "ir.actions.act_window", "name": "Rejected",
                "res_model": "product.requisition", "view_mode": "list,form",
                "domain": [("state", "=", "rejected")]}

    def action_open_cancelled(self):
        return {"type": "ir.actions.act_window", "name": "Cancelled",
                "res_model": "product.requisition", "view_mode": "list,form",
                "domain": [("state", "=", "cancelled")]}

    def action_open_rfq_created(self):
        return {"type": "ir.actions.act_window", "name": "RFQ Created",
                "res_model": "product.requisition", "view_mode": "list,form",
                "domain": [("state", "=", "rfq_created")]}

    def action_open_done(self):
        return {"type": "ir.actions.act_window", "name": "Done",
                "res_model": "product.requisition", "view_mode": "list,form",
                "domain": [("state", "=", "done")]}

    def action_open_pending_mine(self):
        return {"type": "ir.actions.act_window", "name": "Pending My Approval",
                "res_model": "product.requisition", "view_mode": "list,form",
                "domain": [("state", "=", "in_approval"), ("current_approver_id", "=", self.env.uid)]}
