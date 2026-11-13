class SignedInFixture:
    """Explicit signed-in identity for isolated business/UI tests; never used by the app."""

    def current(self, token):
        return dict(id='test-player', display_name='Test player', role='user',
                    discord_user_id='123456789012345678', password_set=True, can_set_password=False)
