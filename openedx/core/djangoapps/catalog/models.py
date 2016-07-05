"""Models controlling integration with the catalog service."""
from urlparse import urljoin

from django.utils.translation import ugettext_lazy as _
from django.db import models

from config_models.models import ConfigurationModel


class CatalogConfig(ConfigurationModel):
    """
    Manages configuration for connecting to the Catalog service and using its API.
    """
    CACHE_KEY = 'catalog.api.data'
    API_NAME = 'catalog'

    api_version_number = models.IntegerField(verbose_name=_('API Version'))

    # TODO: Use internal API gateway?
    internal_service_url = models.URLField(
        verbose_name=_('Internal Service URL'),
        help_text=_(
            'Service URL root, to be used for server-to-server requests (e.g., https://service-internal.example.com)'
        )
    )

    cache_ttl = models.PositiveIntegerField(
        verbose_name=_('Cache Time To Live'),
        default=0,
        help_text=_(
            'Specified in seconds. Enable caching by setting this to a value greater than 0.'
        )
    )

    @property
    def internal_api_url(self):
        """
        Generate a URL based on internal service URL and API version number.
        """
        return urljoin(self.internal_service_url, '/api/v{}/'.format(self.api_version_number))

    @property
    def is_cache_enabled(self):
        """Whether responses from the Catalog API will be cached."""
        return self.cache_ttl > 0
