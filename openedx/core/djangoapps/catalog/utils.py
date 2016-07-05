from edx_rest_api_client.client import EdxRestApiClient

from openedx.core.djangoapps.catalog.models import CatalogConfig
from openedx.core.lib.edx_api_utils import get_edx_api_data


def get_run_marketing_url(course_key, user):
    """Get a course run's marketing URL from the course catalog service.

    Arguments:
        course_key (CourseKey): Course key object identifying the run whose marketing URL we want.
        user (User): The user to authenticate as when making requests to the catalog service.

    Returns:
        string, the marketing URL, or None if no URL is available.
    """
    catalog_config = CatalogConfig.current()

    # TODO: Extract and use AccessTokenView._generate_jwt() to get a JWT for use here.
    api = EdxRestApiClient(api_config.internal_api_url, jwt=jwt)

    data = get_edx_api_data(
        catalog_config,
        user,
        'course_runs',
        resource_id=unicode(course_key),
        cache_key=catalog_config.CACHE_KEY,
        # Sweet dependency injection, bro.
        api=api,
    )

    # TODO: This URL will come with UTM parameters attached.
    # For example, "https://www.edx.org/course/managing-addiction-framework-successful-adelaidex-addictionx?utm_source=r_lucioni&utm_medium=affiliate_partner"
    # Strip these before returning.
    return data.get('marketing_url')
