from rest_framework.throttling import SimpleRateThrottle


class PublicBookingSlotsThrottle(SimpleRateThrottle):
    scope = "public_booking_slots"
    rate = "20/min"

    def get_cache_key(self, request, view):
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }


class PublicBookingCreateThrottle(SimpleRateThrottle):
    scope = "public_booking_create"
    rate = "5/min"

    def get_cache_key(self, request, view):
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }
