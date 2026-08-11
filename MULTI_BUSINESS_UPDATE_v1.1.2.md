# GST Billing Utility v1.1.2

## Multi-business user creation and confirmations

- Added persistent application setting `allow_user_business_creation`.
- Default is OFF.
- Administrator can enable/disable the option from **Users → Business Creation Permission**.
- When enabled, a non-Administrator User can create a Business from **Business Setup**.
- The creating User is automatically granted access to the new Business.
- A Business stores `created_by_user_id`; the creator can edit the Business Setup they created.
- A User cannot edit another user's Business, even if the User has access to it. Administrators can edit all Businesses.
- Existing businesses remain intact; their creator is left unset and therefore remains Administrator-managed.
- Success messages for actions that rerun the Streamlit page now survive the rerun and are displayed after completion.
- Version: 1.1.2
