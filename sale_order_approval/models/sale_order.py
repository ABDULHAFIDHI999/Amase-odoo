# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # ------------------------------------------------------------------
    # Fields
    # ------------------------------------------------------------------

    approver_id = fields.Many2one(
        comodel_name='res.users',
        string='Approver',
        tracking=True,
        copy=False,
        domain=[('share', '=', False), ('active', '=', True)],
        help="The user who will be asked to approve this quotation before it is confirmed.",
    )

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

    # Controls visibility of Approve / Refuse buttons in the view.
    # True for: members of the approver group, Sales Managers, and
    # system administrators — so admins never get locked out.
    is_approver = fields.Boolean(
        string='Is Approver',
        compute='_compute_is_approver',
    )

    # ------------------------------------------------------------------
    # Computed
    # ------------------------------------------------------------------

    @api.depends('company_id')
    def _compute_require_approval(self):
        for order in self:
            order.require_approval = order.company_id.sale_order_approval

    def _compute_is_approver(self):
        user = self.env.user
        is_approver = (
            user.has_group('sale_order_approval.group_sale_order_approver')
            or user.has_group('base.group_system')
            or user._is_admin()
        )
        for order in self:
            order.is_approver = is_approver

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _user_is_approver(self):
        """Return True if the current user may approve/refuse orders."""
        user = self.env.user
        return (
            user.has_group('sale_order_approval.group_sale_order_approver')
            or user.has_group('base.group_system')
            or user._is_admin()
        )

    # ------------------------------------------------------------------
    # Overrides
    # ------------------------------------------------------------------

    def action_confirm(self):
        """Override: if approval is required and not yet approved, block."""
        orders_needing_approval = self.filtered(
            lambda o: o.require_approval and o.approval_state != 'approved'
        )
        if orders_needing_approval:
            # No one bypasses when approval is enabled — they must go
            # through action_submit_for_approval → action_approve.
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
            if not order.approver_id:
                raise UserError(
                    _("Please select an Approver on quotation '%s' before submitting for approval.", order.name)
                )

        self.write({
            'approval_state': 'pending',
            'approved_by': False,
            'approval_date': False,
            'approval_note': False,
        })

        for order in self:
            order.message_post(
                body=_("Quotation submitted for approval by %s. Waiting for %s.",
                       self.env.user.name, order.approver_id.name),
                subtype_xmlid='mail.mt_note',
            )
            # Schedule a To-Do activity on the selected approver
            order.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=order.approver_id.id,
                summary=_('Sales Order Approval Required'),
                note=_(
                    'The quotation <b>%s</b> for customer <b>%s</b> '
                    'submitted by <b>%s</b> requires your approval.',
                    order.name,
                    order.partner_id.name,
                    self.env.user.name,
                ),
            )
        return True

    def action_approve(self):
        """Approve submitted sales orders and confirm them."""
        if not self._user_is_approver():
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
                body=_("Quotation approved by %s and confirmed as a Sales Order.", self.env.user.name),
                subtype_xmlid='mail.mt_note',
            )
        # Confirm the orders after approval
        return super(SaleOrder, self).action_confirm()

    def action_refuse(self):
        """Refuse submitted sales orders — sends them back to Draft."""
        if not self._user_is_approver():
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
                body=_("Quotation refused by %s. Returned to Draft.", self.env.user.name),
                subtype_xmlid='mail.mt_note',
            )
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
