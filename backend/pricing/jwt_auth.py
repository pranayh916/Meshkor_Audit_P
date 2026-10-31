import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed


class AccessTokenAuthentication(BaseAuthentication):
    """Validate short-lived, first-party HS256 bearer access tokens."""

    def authenticate(self, request):
        header = get_authorization_header(request).split()
        if not header:
            return None
        if len(header) != 2 or header[0].lower() != b"bearer":
            raise AuthenticationFailed("Invalid authorization header.")
        User = get_user_model()
        try:
            claims = jwt.decode(header[1], settings.SECRET_KEY, algorithms=["HS256"],
                                options={"require": ["sub", "exp", "iat", "type"]})
            if claims["type"] != "access":
                raise AuthenticationFailed("Invalid access token.")
            user = User.objects.get(pk=claims["sub"], is_active=True)
        except (jwt.PyJWTError, User.DoesNotExist, ValueError, TypeError):
            raise AuthenticationFailed("Invalid or expired access token.")
        return user, claims

    def authenticate_header(self, request):
        return "Bearer"

