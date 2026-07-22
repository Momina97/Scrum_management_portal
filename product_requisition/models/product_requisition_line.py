from odoo import models, fields, api


class ProductRequisitionLine(models.Model):
    _name = "product.requisition.line"
    _description = "Product Requisition Line"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    requisition_id = fields.Many2one(
        "product.requisition",
        string="Requisition",
        required=True,
        ondelete="cascade",
    )
    product_id = fields.Many2one(
        "product.product",
        string="Product",
        required=True,
        domain=[("type", "in", ["product", "consu"])],
    )
    description = fields.Char(
        string="Description",
        compute="_compute_description",
        store=True,
        readonly=False,
    )
    qty_requested = fields.Float(string="Requested Qty", required=True, default=1.0)
    product_uom_id = fields.Many2one(
        "uom.uom",
        string="Unit of Measure",
        compute="_compute_product_uom",
        store=True,
        readonly=False,
    )
    qty_on_hand = fields.Float(
        string="On Hand",
        related="product_id.qty_available",
        readonly=True,
    )
    part_no = fields.Char(
        string="Part No.",
        help="Manufacturer / supplier part number for this item.",
    )
    estimated_unit_price = fields.Float(
        string="Est. Unit Price",
        digits="Product Price",
        help="Estimated unit price used as the starting price_unit on the generated RFQ.",
    )
    na_certificate = fields.Boolean(
        string="NA Cert.",
        default=False,
        help="Non-Availability certificate required or issued for this item.",
    )
    stock_status = fields.Selection(
        [('available', 'Available'), ('partial', 'Partial'), ('unavailable', 'Unavailable')],
        string='Stock Status',
        compute='_compute_stock_status',
        store=False,
    )

    @api.depends("product_id")
    def _compute_description(self):
        for line in self:
            line.description = line.product_id.display_name or ""

    @api.depends("product_id")
    def _compute_product_uom(self):
        for line in self:
            line.product_uom_id = (
                line.product_id.uom_id if line.product_id else False
            )

    @api.depends('qty_requested', 'qty_on_hand')
    def _compute_stock_status(self):
        for line in self:
            if not line.product_id:
                line.stock_status = False
                continue
            if line.qty_on_hand >= line.qty_requested:
                line.stock_status = 'available'
            elif line.qty_on_hand > 0:
                line.stock_status = 'partial'
            else:
                line.stock_status = 'unavailable'
