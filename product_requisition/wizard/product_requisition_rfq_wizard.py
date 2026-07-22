from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ProductRequisitionRfqWizard(models.TransientModel):
    """
    Wizard to create one or more draft Purchase Orders (RFQs) from an
    approved Product Requisition.

    Workflow
    --------
    • Local  → company currency, no incoterm required.
    • Foreign → foreign currency (defaults to USD), incoterm recommended.

    Multiple vendors may be selected; one RFQ is created per vendor so
    that the procurement team can compare quotes using Odoo's native
    "Compare Order Lines" feature (CST step).
    """

    _name = "product.requisition.rfq.wizard"
    _description = "Create RFQ(s) from Requisition"

    # ── Read-only context ─────────────────────────────────────────────────

    requisition_id = fields.Many2one(
        "product.requisition",
        string="Requisition",
        required=True,
        readonly=True,
    )
    requisition_name = fields.Char(
        related="requisition_id.name",
        string="Reference",
        readonly=True,
    )
    purchase_mode = fields.Selection(
        related="requisition_id.purchase_mode",
        string="Purchase Mode",
        readonly=True,
    )
    purchase_option = fields.Selection(
        related="requisition_id.purchase_option",
        string="Purchase Option",
        readonly=True,
    )
    purchase_type = fields.Selection(
        related="requisition_id.purchase_type",
        string="Type",
        readonly=True,
    )
    department_name = fields.Char(
        related="requisition_id.department_id.name",
        string="Department",
        readonly=True,
    )

    # ── Vendor selection ──────────────────────────────────────────────────

    vendor_ids = fields.Many2many(
        "res.partner",
        string="Vendor(s)",
        domain="[('is_company', '=', True)]",
        help=(
            "Select one or more vendors.\n"
            "One RFQ will be created per vendor so you can compare quotes "
            "using the 'Compare Order Lines' button in the purchase module."
        ),
    )

    # ── RFQ settings ──────────────────────────────────────────────────────

    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    incoterm_id = fields.Many2one(
        "account.incoterms",
        string="Incoterm",
        help="Delivery term / incoterm for the RFQ (e.g. DDP, CPT, CIF).",
    )
    payment_term_id = fields.Many2one(
        "account.payment.term",
        string="Payment Terms",
    )
    date_order = fields.Date(
        string="Order Deadline",
        help="Expected date by which vendors should respond.",
    )
    rfq_notes = fields.Text(
        string="Notes for RFQ",
        help="Will be added to the internal notes of each created RFQ.",
    )

    # ── Defaults / onchange ───────────────────────────────────────────────

    @api.onchange("requisition_id")
    def _onchange_requisition_id(self):
        """Auto-set USD when purchase mode is Foreign."""
        if self.requisition_id and self.requisition_id.purchase_mode == "foreign":
            usd = self.env.ref("base.USD", raise_if_not_found=False)
            if usd:
                self.currency_id = usd

    # ── Helpers ───────────────────────────────────────────────────────────

    def _build_order_lines(self):
        """Return a fresh (0,0,{…}) command list for purchase.order.line."""
        req = self.requisition_id
        lines = []
        for line in req.requisition_line_ids:
            name = line.description or line.product_id.display_name or ""
            if line.part_no:
                name = f"[{line.part_no}] {name}".strip()
            lines.append((0, 0, {
                "product_id":   line.product_id.id,
                "name":         name,
                "product_qty":  line.qty_requested,
                "product_uom":  line.product_uom_id.id,
                "price_unit":   line.estimated_unit_price or 0.0,
                "date_planned": (
                    req.date_required or fields.Date.today()
                ),
            }))
        return lines

    # ── Main action ───────────────────────────────────────────────────────

    def action_create_rfqs(self):
        """
        Create one draft purchase.order (RFQ) per selected vendor.
        If no vendor is selected, one RFQ is created without a vendor.
        """
        self.ensure_one()
        req = self.requisition_id

        if not req.requisition_line_ids:
            raise UserError(_("No product lines found on this requisition."))

        common_vals = {
            "origin":      req.name,
            "currency_id": self.currency_id.id,
            "notes":       self.rfq_notes or req.notes or "",
        }
        if self.incoterm_id:
            common_vals["incoterm_id"] = self.incoterm_id.id
        if self.payment_term_id:
            common_vals["payment_term_id"] = self.payment_term_id.id
        if self.date_order:
            common_vals["date_order"] = self.date_order

        # Iterate over selected vendors; if none chosen, create one RFQ
        vendors = list(self.vendor_ids) if self.vendor_ids else [None]
        created_ids = []

        for vendor in vendors:
            vals = dict(common_vals)
            vals["order_line"] = self._build_order_lines()
            if vendor:
                vals["partner_id"] = vendor.id
            rfq = self.env["purchase.order"].with_context(
                default_requisition_id=False
            ).create(vals)
            created_ids.append(rfq.id)

        # Advance requisition state
        if req.state == "approved":
            req.write({"state": "rfq_created"})

        # Open result
        if len(created_ids) == 1:
            return {
                "type":      "ir.actions.act_window",
                "name":      _("Request for Quotation"),
                "res_model": "purchase.order",
                "res_id":    created_ids[0],
                "view_mode": "form",
                "target":    "current",
            }
        return {
            "type":      "ir.actions.act_window",
            "name":      _("Requests for Quotation — %s") % req.name,
            "res_model": "purchase.order",
            "view_mode": "list,form",
            "domain":    [("id", "in", created_ids)],
            "target":    "current",
        }
