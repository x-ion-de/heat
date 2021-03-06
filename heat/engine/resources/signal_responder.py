#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from keystoneclient.contrib.ec2 import utils as ec2_utils
from oslo_config import cfg
from oslo_log import log as logging
from six.moves.urllib import parse as urlparse

from heat.common.i18n import _LW
from heat.engine.resources import stack_user

LOG = logging.getLogger(__name__)

SIGNAL_TYPES = (
    WAITCONDITION, SIGNAL
) = (
    '/waitcondition', '/signal'
)
SIGNAL_VERB = {WAITCONDITION: 'PUT',
               SIGNAL: 'POST'}


class SignalResponder(stack_user.StackUser):

    # Anything which subclasses this may trigger authenticated
    # API operations as a consequence of handling a signal
    requires_deferred_auth = True

    def handle_create(self):
        super(SignalResponder, self).handle_create()
        self._create_keypair()

    def handle_delete(self):
        super(SignalResponder, self).handle_delete()
        self._delete_signed_url()

    def _delete_signed_url(self):
        self.data_delete('ec2_signed_url')

    def _get_signed_url(self, signal_type=SIGNAL):
        """Create properly formatted and pre-signed URL.

        This uses the created user for the credentials.

        See boto/auth.py::QuerySignatureV2AuthHandler

        :param signal_type: either WAITCONDITION or SIGNAL.
        """
        stored = self.data().get('ec2_signed_url')
        if stored is not None:
            return stored

        access_key = self.data().get('access_key')
        secret_key = self.data().get('secret_key')

        if not access_key or not secret_key:
            LOG.warn(_LW('Cannot generate signed url, '
                         'no stored access/secret key'))
            return

        config_url = cfg.CONF.heat_waitcondition_server_url
        if config_url:
            signal_url = config_url.replace('/waitcondition', signal_type)
        else:
            heat_client_plugin = self.stack.clients.client_plugin('heat')
            endpoint = heat_client_plugin.get_heat_cfn_url()
            signal_url = ''.join([endpoint, signal_type])

        host_url = urlparse.urlparse(signal_url)

        path = self.identifier().arn_url_path()

        # Note the WSGI spec apparently means that the webob request we end up
        # processing in the CFN API (ec2token.py) has an unquoted path, so we
        # need to calculate the signature with the path component unquoted, but
        # ensure the actual URL contains the quoted version...
        unquoted_path = urlparse.unquote(host_url.path + path)
        request = {'host': host_url.netloc.lower(),
                   'verb': SIGNAL_VERB[signal_type],
                   'path': unquoted_path,
                   'params': {'SignatureMethod': 'HmacSHA256',
                              'SignatureVersion': '2',
                              'AWSAccessKeyId': access_key,
                              'Timestamp':
                              self.created_time.strftime("%Y-%m-%dT%H:%M:%SZ")
                              }}
        # Sign the request
        signer = ec2_utils.Ec2Signer(secret_key)
        request['params']['Signature'] = signer.generate(request)

        qs = urlparse.urlencode(request['params'])
        url = "%s%s?%s" % (signal_url.lower(),
                           path, qs)

        self.data_set('ec2_signed_url', url)
        return url

    def _get_signal_url(self):
        stored = self.data().get('signal_url')
        if stored is not None:
            return stored

        url = self.client_plugin('heat').get_heat_url()
        host_url = urlparse.urlparse(url)
        path = self.identifier().url_path()

        url = urlparse.urlunsplit(
            (host_url.scheme, host_url.netloc, 'v1/%s/signal' % path, '', ''))

        self.data_set('signal_url', url)
        return url
