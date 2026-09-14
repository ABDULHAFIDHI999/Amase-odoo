# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # ------------------------------------------------------------------
    # Fields
    # ------------------------------------------------------------------

    approval_state = fields.Selection(
        selection=[
            ('pending', 'Pending Approval'),
            ('approved', 'Approved'),
            ('refused', 'Refused'),
        ],
        string='Approval Status',
        copy=False,
        tracking=True,
    )

    approved_by = fields.Many2one(
        comodel_name='res.users',
        string='Approved / Refused By',
        copy=False,
        tracking=True,
    )

    approval_date = fields.Datetime(
        string='Approval Date',
        copy=False,
        tracking=True,
    )

    approval_note = fields.Text(
        string='Approval Note',
        copy=False,
    )

    # Convenience boolean so views can hide/show things easily
    require_approval = fields.Boolean(
        string='Requires Approval',
        compute='_compute_require_approval',
    )

    # ------------------------------------------------------------------
    # Computed
    # ------------------------------------------------------------------

    @api.depends('company_id')
    def _compute_require_approval(self):
        for order in self:
            order.require_approval = order.company_id.sale_order_approval

    # ------------------------------------------------------------------
    # Overrides
    # ------------------------------------------------------------------

    def action_confirm(self):
        """Override: if approval is required and the order is not yet
        approved, redirect to the approval submission instead."""
        orders_needing_approval = self.filtered(
            lambda o: o.require_approval and o.approval_state != 'approved'
        )
        if orders_needing_approval:
            # Only Sales Managers can bypass the approval gate
            if not self.env.user.has_group('sale_order_approval.group_sale_order_approver'):
                return orders_needing_approval.action_submit_for_approval()
        return super().action_confirm()

    # ------------------------------------------------------------------
    # Approval actions
    # ------------------------------------------------------------------

    def action_submit_for_approval(self):
        """Submit the quotation/order for manager approval."""
        for order in self:
            if order.state not in ('draft', 'sent'):
                raise UserError(
                    _("Only quotations in Draft or Sent state can be submitted for approval.")
                )
        self.write({
            'approval_state': 'pending',
            'approved_by': False,
            'approval_date': False,
            'approval_note': False,
        })
        for order in self:
            order.message_post(
                body=_("Order submitted for approval by %s.", order.env.user.name),
                subtype_xmlid='mail.mt_note',
            )
        # Notify approvers via activity
        approver_group = self.env.ref(
            'sale_order_approval.group_sale_order_approver', raise_if_not_found=False
        )
        if approver_group:
            approvers = approver_group.all_user_ids.filtered(
                lambda u: u.active and u != self.env.user
            )
            for order in self:
                for approver in approvers:
                    order.activity_schedule(
                        'mail.mail_activity_data_todo',
                        user_id=approver.id,
                        summary=_('Sales Order Approval Required'),
                        note=_(
                            'The sales order %s requires your approval.',
                            order.name,
                        ),
                    )
        return True

    def action_approve(self):
        """Approve submitted sales orders and confirm them."""
        if not self.env.user.has_group('sale_order_approval.group_sale_order_approver'):
            raise UserError(_("Only Sales Order Approvers can approve orders."))
        for order in self:
            if order.approval_state != 'pending':
                raise UserError(
                    _("Only orders pending approval can be approved.")
                )
        self.write({
            'approval_state': 'approved',
            'approved_by': self.env.uid,
            'approval_date': fields.Datetime.now(),
        })
        for order in self:
            order.activity_feedback(
                ['mail.mail_activity_data_todo'],
                feedback=_('Approved by %s.', self.env.user.name),
            )
            order.message_post(
                body=_("Order approved by %s.", self.env.user.name),
                subtype_xmlid='mail.mt_note',
            )
        # Now actually confirm the orders
        return super(SaleOrder, self).action_confirm()

    def action_refuse(self):
        """Refuse submitted sales orders — sends them back to Draft."""
        if not self.env.user.has_group('sale_order_approval.group_sale_order_approver'):
            raise UserError(_("Only Sales Order Approvers can refuse orders."))
        for order in self:
            if order.approval_state != 'pending':
                raise UserError(
                    _("Only orders pending approval can be refused.")
                )
        self.write({
            'approval_state': 'refused',
            'approved_by': self.env.uid,
            'approval_date': fields.Datetime.now(),
        })
        for order in self:
            order.activity_feedback(
                ['mail.mail_activity_data_todo'],
                feedback=_('Refused by %s.', self.env.user.name),
            )
            order.message_post(
                body=_("Order refused by %s. Returned to Draft.", self.env.user.name),
                subtype_xmlid='mail.mt_note',
            )
        # Reset approval state and send back to draft
        return self.write({'approval_state': False})

    def action_draft(self):
        """Reset to draft also clears approval state."""
        res = super().action_draft()
        self.filtered(lambda o: o.approval_state == 'refused').write({
            'approval_state': False,
            'approved_by': False,
            'approval_date': False,
        })
        return res
