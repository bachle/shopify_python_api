import pyactiveresource.connection
from pyactiveresource.activeresource import ActiveResource, ResourceMeta
import pyactiveresource.util as util
import shopify.yamlobjects
import shopify.mixins as mixins
import shopify
import threading
import urllib
import urllib2
import urlparse
import sys

# Store the response from the last request in the connection object
class ShopifyConnection(pyactiveresource.connection.Connection):
    response = None
    def _open(self, *args, **kwargs):
        self.response = None
        try:
            self.response = super(ShopifyConnection, self)._open(*args, **kwargs)
        except pyactiveresource.connection.ConnectionError, err:
            self.response = err.response
            raise
        return self.response

# Inherit from pyactiveresource's metaclass in order to use ShopifyConnection
class ShopifyResourceMeta(ResourceMeta):
    @property
    def connection(cls):
        """HTTP connection for the current thread"""
        local = cls._threadlocal
        if not getattr(local, 'connection', None):
            # Make sure these variables are no longer affected by other threads.
            local.user = cls.user
            local.password = cls.password
            local.site = cls.site
            local.timeout = cls.timeout
            local.headers = cls.headers
            local.format = cls.format
            if cls.site is None:
                raise ValueError("No shopify session is active")
            local.connection = ShopifyConnection(
                cls.site, cls.user, cls.password, cls.timeout, cls.format)
        return local.connection

    def get_user(cls):
        return getattr(cls._threadlocal, 'user', ShopifyResource._user)

    def set_user(cls, value):
        cls._threadlocal.connection = None
        ShopifyResource._user = cls._threadlocal.user = value

    user = property(get_user, set_user, None,
                    "The username for HTTP Basic Auth.")

    def get_password(cls):
        return getattr(cls._threadlocal, 'password', ShopifyResource._password)

    def set_password(cls, value):
        cls._threadlocal.connection = None
        ShopifyResource._password = cls._threadlocal.password = value

    password = property(get_password, set_password, None,
                        "The password for HTTP Basic Auth.")

    def get_site(cls):
        return getattr(cls._threadlocal, 'site', ShopifyResource._site)

    def set_site(cls, value):
        cls._threadlocal.connection = None
        ShopifyResource._site = cls._threadlocal.site = value
        if value is not None:
            host = urlparse.urlsplit(value)[1]
            auth_info, host = urllib2.splituser(host)
            if auth_info:
                user, password = urllib2.splitpasswd(auth_info)
                if user:
                    cls.user = urllib.unquote(user)
                if password:
                    cls.password = urllib.unquote(password)

    site = property(get_site, set_site, None,
                    'The base REST site to connect to.')

    def get_timeout(cls):
        return getattr(cls._threadlocal, 'timeout', ShopifyResource._timeout)

    def set_timeout(cls, value):
        cls._threadlocal.connection = None
        ShopifyResource._timeout = cls._threadlocal.timeout = value

    timeout = property(get_timeout, set_timeout, None,
                       'Socket timeout for HTTP requests')

    def get_headers(cls):
        if not hasattr(cls._threadlocal, 'headers'):
            cls._threadlocal.headers = ShopifyResource._headers.copy()
        return cls._threadlocal.headers

    def set_headers(cls, value):
        cls._threadlocal.headers = value

    headers = property(get_headers, set_headers, None,
                       'The headers sent with HTTP requests')

    def get_format(cls):
        return getattr(cls._threadlocal, 'format', ShopifyResource._format)

    def set_format(cls, value):
        cls._threadlocal.connection = None
        ShopifyResource._format = cls._threadlocal.format = value

    format = property(get_format, set_format, None,
                      'Encoding used for request and responses')

    def get_primary_key(cls):
        return cls._primary_key

    def set_primary_key(cls, value):
        cls._primary_key = value

    primary_key = property(get_primary_key, set_primary_key, None,
                           'Name of attribute that uniquely identies the resource')


class ShopifyResource(ActiveResource, mixins.Countable):
    __metaclass__ = ShopifyResourceMeta
    _primary_key = "id"
    _threadlocal = threading.local()
    _headers = { 'User-Agent': 'ShopifyPythonAPI/%s Python/%s' % (shopify.VERSION, sys.version.split(' ', 1)[0]) }

    def __init__(self, attributes=None, prefix_options=None):
        if attributes is not None and prefix_options is None:
            prefix_options, attributes = self.__class__._split_options(attributes)
        return super(ShopifyResource, self).__init__(attributes, prefix_options)

    def is_new(self):
        return not self.id

    def _load_attributes_from_response(self, response):
        self._update(self.__class__.format.decode(response.body))

    def __get_id(self):
        return self.attributes.get(self.klass.primary_key)

    def __set_id(self, value):
        self.attributes[self.klass.primary_key] = value

    id = property(__get_id, __set_id, None, 'Value stored in the primary key')

    # Backport changes to _update, to_dict and to_xml from upstream
    # patch to suport loading:
    # https://groups.google.com/forum/#!msg/pyactiveresource/JpE-Qg_pEZc/RlrbQFafk3IJ
    def _update(self, attributes):
        if not isinstance(attributes, dict):
            return
        for key, value in attributes.items():
            if isinstance(value, dict):
                klass = self._find_class_for(key)
                attr = klass(value)
            elif isinstance(value, list):
                klass = None
                attr = []
                for child in value:
                    if isinstance(child, dict):
                        if klass is None:
                            klass = self._find_class_for_collection(key)
                        attr.append(klass(child))
                    else:
                        attr.append(child)
            else:
                attr = value
            self.attributes[key] = attr

    def to_dict(self):
        values = {}
        for key, value in self.attributes.iteritems():
            if isinstance(value, list):
                new_value = []
                for item in value:
                  if isinstance(item, ActiveResource):
                      new_value.append(item.to_dict())
                  else:
                      new_value.append(item)
                values[key] = new_value
            elif isinstance(value, ActiveResource):
                values[key] = value.to_dict()
            else:
                values[key] = value
        return values

    @staticmethod
    def __to_xml_element(obj, root, dasherize):
        root = dasherize and root.replace('_', '-') or root
        root_element = util.ET.Element(root)
        if isinstance(obj, list):
            root_element.set('type', 'array')
            for value in obj:
                root_element.append(ShopifyResource.__to_xml_element(value, util.singularize(root), dasherize))
        elif isinstance(obj, dict):
            for key, value in obj.iteritems():
                root_element.append(ShopifyResource.__to_xml_element(value, key, dasherize))
        else:
            util.serialize(obj, root_element)

        return root_element

    def to_xml(self, root=None, header=True, pretty=False, dasherize=True):
        if not root:
            root = self._singular
        root_element = ShopifyResource.__to_xml_element(self.to_dict(), root, dasherize)
        if pretty:
            xml_pretty_format(root_element)
        xml_data = util.ET.tostring(root_element)
        if header:
            return util.XML_HEADER + '\n' + xml_data
        return xml_data



    @classmethod
    def activate_session(cls, session):
        cls.site = session.site
        if not session.legacy:
            cls.user = None
            cls.password = None
            cls.headers['X-Shopify-Access-Token'] = session.token

    @classmethod
    def clear_session(cls):
        cls.site = None
        cls.user = None
        cls.password = None
        if 'X-Shopify-Access-Token' in cls.headers:
            del cls.headers['X-Shopify-Access-Token']
