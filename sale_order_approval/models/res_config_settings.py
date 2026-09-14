# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    sale_order_approval = fields.Boolean(
        string='Sales Order Approval',
        default=False,
    )


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    sale_order_approval = fields.Boolean(
        string='Sales Order Approval',
        related='company_id.sale_order_approval',
        readonly=False,
        help="Require manager approval before a sales order can be confirmed.",
    )
