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
        help="The user who will be asked to approve this quotation before it is confirmed.",
    )

    # Computed domain: only administrator-role users, excluding the
    # current user, so a salesperson cannot pick themselves.
    approver_candidate_ids = fields.Many2many(
        comodel_name='res.users',
        string='Eligible Approvers',
        compute='_compute_approver_candidate_ids',
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

    require_approval = fields.Boolean(
        string='Requires Approval',
        compute='_compute_require_approval',
    )

    # True for members of the approver group, system admins, and
    # superuser — controls button visibility without using groups=.
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

    def _compute_approver_candidate_ids(self):
        """Return users who may act as approvers, excluding the current user.

        Candidates are:
        - Users in base.group_system  (Role / Administrator)
        - Users in sale_order_approval.group_sale_order_approver
        Excluding the logged-in user so a salesperson cannot pick themselves.
        """
        system_group = self.env.ref('base.group_system', raise_if_not_found=False)
        approver_group = self.env.ref(
            'sale_order_approval.group_sale_order_approver', raise_if_not_found=False
        )

        candidate_ids = set()
        if system_group:
            candidate_ids.update(system_group.user_ids.ids)
        if approver_group:
            candidate_ids.update(approver_group.user_ids.ids)

        # Never include the current user in the list
        candidate_ids.discard(self.env.uid)

        candidates = self.env['res.users'].browse(list(candidate_ids)).filtered(
            lambda u: u.active and not u.share
        )
        for order in self:
            order.approver_candidate_ids = candidates

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
                    _("Please select an Approver on quotation '%s' before submitting for approval.",
                      order.name)
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
                raise UserError(_("Only orders pending approval can be approved."))
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
                body=_("Quotation approved by %s and confirmed as a Sales Order.",
                       self.env.user.name),
                subtype_xmlid='mail.mt_note',
            )
        return super(SaleOrder, self).action_confirm()

    def action_refuse(self):
        """Refuse submitted sales orders — sends them back to Draft."""
        if not self._user_is_approver():
            raise UserError(_("Only Sales Order Approvers can refuse orders."))
        for order in self:
            if order.approval_state != 'pending':
                raise UserError(_("Only orders pending approval can be refused."))
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
