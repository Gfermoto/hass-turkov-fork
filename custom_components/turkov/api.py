import asyncio
import logging
from functools import wraps
from json import JSONDecodeError, loads
from types import MappingProxyType
from typing import (
    Optional,
    TypedDict,
    ClassVar,
    Dict,
    List,
    Mapping,
    MutableMapping,
    Union,
    Set,
    Tuple,
    Callable,
    Any,
    SupportsInt,
)

import aiohttp
from aiohttp import ContentTypeError
from aiohttp.hdrs import METH_GET, IF_NONE_MATCH, METH_POST, ETAG
from aiohttp.typedefs import LooseHeaders
from aiohttp.web_exceptions import HTTPForbidden, HTTPUnauthorized
from homeassistant.util.dt import utcnow
from multidict import CIMultiDict

_LOGGER = logging.getLogger(__name__)


class DeviceDataResponseDict(TypedDict):
    _id: str
    serialNumber: Optional[str]
    pin: Optional[str]
    deviceType: Optional[str]
    deviceName: Optional[str]
    firmVer: Optional[str]
    image: Optional[str]


class UserDataResponseDict(TypedDict):
    devices: List[DeviceDataResponseDict]
    pushTokens: List[str]
    userEmail: str
    firstName: str
    lastName: str
    fathersName: str


class ErrorResponseDict(TypedDict):
    message: str


class SignInResponseDict(TypedDict):
    accessToken: str
    accessTokenExpiresAt: int
    refreshToken: str
    refreshTokenExpiresAt: int


class TurkovAPIError(Exception):
    """Base class for Turkov API errors"""


class TurkovAPIAuthenticationError(TurkovAPIError):
    """Authentication-related exceptions"""


class TurkovAPIValueError(TurkovAPIError, ValueError):
    """Data-related errors"""


def _log_hide_id(id_: str):
    return "*" + str(id_)[-4:]


class TurkovAPI:
    @staticmethod
    def _handle_preliminary_auth(fn):
        @wraps(fn)
        async def decorator(self: "TurkovAPI", *args, **kwargs):
            authentication_attempted = False
            handle_authentication = self.handle_authentication

            # Handle authentication (if enabled)
            if handle_authentication and self.access_token_needs_update:
                _LOGGER.debug(
                    f"[{self}] Access token requires update before request"
                )
                await self.authenticate()
                authentication_attempted = True

            # Perform execution
            try:
                return await fn(self, *args, **kwargs)
            except (
                TurkovAPIAuthenticationError,
                HTTPForbidden,
                HTTPUnauthorized,
            ) as exc:
                if authentication_attempted or not handle_authentication:
                    if isinstance(exc, TurkovAPIAuthenticationError):
                        raise
                    raise TurkovAPIAuthenticationError(
                        "Unauthorized request performed"
                    ) from exc
                _LOGGER.debug(
                    f"[{self}] Performing authentication because previous request failed due to authentication errors"
                )
                await self.authenticate()
                return await fn(self, *args, **kwargs)

        return decorator

    BASE_URL: ClassVar[str] = "https://turkovwifi.ru"

    def __str__(self) -> str:
        return f"{self.__class__.__name__}[{'**'.join(v[0] for v in self._user_email.partition('@')) + '**'}]"

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}[user_email={self._user_email}, devices={self._devices}]>"

    def __init__(
        self,
        session: aiohttp.ClientSession,
        user_email: str,
        password: str,
        handle_authentication: bool = True,
        *,
        access_token: Optional[str] = None,
        access_token_expires_at: Optional[int] = None,
        refresh_token: Optional[str] = None,
        refresh_token_expires_at: Optional[int] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        middle_name: Optional[str] = None,
    ) -> None:
        # Internals
        self._session = session
        self._devices: Dict[str, TurkovDevice] = {}
        self._request_history: Dict[str, str] = {}
        self.handle_authentication = handle_authentication

        # Required authentication data
        self._user_email = user_email
        self._password = password

        # Optional authentication data
        self._access_token = access_token
        self._access_token_expires_at = access_token_expires_at
        self._refresh_token = refresh_token
        self._refresh_token_expires_at = refresh_token_expires_at
        self.first_name = first_name
        self.last_name = last_name
        self.middle_name = middle_name

    @property
    def devices(self) -> Mapping[str, "TurkovDevice"]:
        return MappingProxyType(self._devices)

    @property
    def user_email(self) -> str:
        return self._user_email

    @property
    def password(self) -> str:
        return self._password

    @property
    def access_token(self) -> Optional[str]:
        return self._access_token

    @property
    def access_token_expires_at(self) -> Optional[int]:
        return self._access_token_expires_at

    @property
    def access_token_needs_update(self) -> bool:
        if not self._access_token:
            return True
        access_token_expires_at = self._access_token_expires_at
        if access_token_expires_at is None:
            return True
        return (access_token_expires_at - 60) < utcnow().timestamp()

    @property
    def refresh_token(self) -> Optional[str]:
        return self._refresh_token

    @property
    def refresh_token_expires_at(self) -> Optional[int]:
        return self._refresh_token_expires_at

    @property
    def refresh_token_needs_update(self) -> bool:
        if not self._refresh_token:
            return True
        refresh_token_expires_at = self._refresh_token_expires_at
        if refresh_token_expires_at is None:
            return True
        return (refresh_token_expires_at - 60) < utcnow().timestamp()

    @property
    def session(self) -> aiohttp.ClientSession:
        return self._session

    @session.setter
    def session(self, value: aiohttp.ClientSession) -> None:
        if not isinstance(value, aiohttp.ClientSession):
            raise ValueError("only a session can be set")
        self._session = value

    async def authenticate_with_email(
        self,
        user_email: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        if not user_email:
            user_email = self._user_email
        if not password:
            password = self._password

        if not (user_email and password):
            raise ValueError("email and/or password empty")

        _LOGGER.info(
            f"[{self}] Preparing to authenticate with email/password combo"
        )
        async with self._session.post(
            self.BASE_URL + "/user/signin",
            json={
                "userEmail": user_email,
                "password": password,
            },
        ) as response:
            await self._process_auth_request(response)

    async def authenticate_with_token(
        self, refresh_token: Optional[str] = None
    ) -> None:
        if not refresh_token:
            if self.refresh_token_needs_update:
                raise RuntimeError("refresh token expired")
            refresh_token = self._refresh_token

        _LOGGER.info(f"[{self}] Preparing to authenticate with refresh token")
        async with self._session.get(
            self.BASE_URL + "/user/token",
            headers={
                "x-access-token": refresh_token,
            },
        ) as response:
            await self._process_auth_request(response)

    async def _process_auth_request(self, request) -> None:
        """@TODO"""
        try:
            async with request as response:
                data = await response.json()
        except (ContentTypeError, JSONDecodeError) as exc:
            raise TurkovAPIAuthenticationError(
                "Server returned bad response"
            ) from exc
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise TurkovAPIAuthenticationError(
                "Server did not respond"
            ) from exc

        _LOGGER.debug(f"[{self}] Authentication response data: {data}")

        # Pin current timestamp
        current_timestamp = utcnow().timestamp()

        try:
            # Extract tokens and expiry information
            access_token = data["accessToken"]
            access_token_expires_at = int(data["accessTokenExpiresAt"])
            refresh_token = data["refreshToken"]
            refresh_token_expires_at = int(data["refreshTokenExpiresAt"])
        except KeyError as exc:
            raise TurkovAPIAuthenticationError(
                f"Server did not provide auth data {exc}: {data.get('message') or '<no message>'}"
            ) from exc
        except (ValueError, TypeError) as exc:
            raise TurkovAPIAuthenticationError(
                f"Server provided bad data: {exc}"
            )

        # Some data validation
        if not (access_token or refresh_token):
            raise TurkovAPIAuthenticationError(
                f"Server provided empty auth data"
            )
        if access_token_expires_at < current_timestamp:
            raise TurkovAPIAuthenticationError(
                f"Server provided expired access token"
            )
        if refresh_token_expires_at < current_timestamp:
            raise TurkovAPIAuthenticationError(
                f"Server provided expired refresh token"
            )

        _LOGGER.info(f"[{self}] Successful authentication, updating data")

        # Update auth data
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._access_token_expires_at = access_token_expires_at
        _LOGGER.debug(
            f"[{self}] Access token expires at: {access_token_expires_at} "
            f"(in {access_token_expires_at - current_timestamp} seconds)"
        )
        self._refresh_token_expires_at = refresh_token_expires_at
        _LOGGER.debug(
            f"[{self}] Refresh token expires at: {access_token_expires_at} "
            f"(in {refresh_token_expires_at - current_timestamp} seconds)"
        )

    async def authenticate(self) -> None:
        if not self.refresh_token_needs_update:
            _LOGGER.debug(f"[{self}] Auth called, refresh not yet expired")
            try:
                await self.authenticate_with_token()
            except asyncio.CancelledError:
                raise
            except BaseException as exp:
                _LOGGER.debug(f"[{self}] Error: {exp}", exc_info=exp)
                _LOGGER.warning(
                    f"[{self}] Failed to refresh access token, using regular auth"
                )
            else:
                return

        await self.authenticate_with_email()

    async def prepare_authenticated_request(
        self,
        *args,
        headers: Optional[LooseHeaders] = None,
        request_tag: Optional[str] = None,
        **kwargs,
    ):
        if headers is None:
            headers = {}
        elif not isinstance(headers, MutableMapping):
            headers = CIMultiDict(headers)

        headers["x-access-token"] = self._access_token

        if request_tag is not None:
            try:
                if_none_match = self._request_history[request_tag]
            except KeyError:
                pass
            else:
                headers[IF_NONE_MATCH] = if_none_match

        return self._session.request(*args, headers=headers, **kwargs)

    @_handle_preliminary_auth
    async def update_user_data(self, force: bool = False) -> None:
        _LOGGER.debug(
            f"[{self}] Updating user information and list of devices"
        )
        request_tag = "user_data"

        async with (
            await self.prepare_authenticated_request(
                METH_GET,
                self.BASE_URL + "/user",
                request_tag=(None if force else request_tag),
            )
        ) as response:
            if not force and response.status == 304:
                _LOGGER.debug(f"[{self}] User data not modified, no updates")
                return

            response_tag = response.headers.get(ETAG)

            try:
                user_data: UserDataResponseDict = await response.json()
            except (JSONDecodeError, ContentTypeError) as exp:
                raise TurkovAPIAuthenticationError(
                    f"Server did not provide user and/or device datum: {exp}"
                ) from exp

        _LOGGER.debug(f"[{self}] User data response: {user_data}")

        try:
            device_datum = user_data["devices"]
            user_email = user_data["userEmail"]
            first_name = user_data["firstName"]
            last_name = user_data["lastName"]
            middle_name = user_data["fathersName"]
        except KeyError as exc:
            raise TurkovAPIError(
                f"Server did not provide user and/or device datum: {exp}"
            ) from exc

        self._user_email = user_email

        # Optional data
        self.first_name = first_name
        self.last_name = last_name
        self.middle_name = middle_name

        existing_devices = self._devices
        leftover_devices = set(existing_devices.keys())
        for device_data in device_datum:
            try:
                id_ = device_data["_id"]
            except KeyError:
                _LOGGER.warning(
                    f"[{self}] Device data does not contain ID: {device_data}"
                )
                continue
            if not id_:
                _LOGGER.warning(
                    f"[{self}] Device data contains empty ID: {device_data}"
                )
                continue

            try:
                device = existing_devices[id_]
                _LOGGER.info(f"[{self}] Found existing device: {device}")
            except KeyError:
                _LOGGER.info(
                    f"[{self}] Creating new device with ID: {_log_hide_id(id_)}"
                )
                device = TurkovDevice(id_, self)
                existing_devices[id_] = device
            else:
                leftover_devices.discard(id_)

            if "deviceType" in device_data:
                device.type = device_data["deviceType"]
            if "deviceName" in device_data:
                device.name = device_data["deviceName"]
            if "serialNumber" in device_data:
                device.serial_number = device_data["serialNumber"]
            if "pin" in device_data:
                device.pin = device_data["pin"]
            if "firmVer" in device_data:
                device.firmware_version = device_data["firmVer"]

        if response_tag:
            self._request_history[request_tag] = response_tag

        # Discard leftover devices
        for id_ in leftover_devices:
            _LOGGER.info(
                f"[{self}] Discarding obsolete device: {existing_devices[id_]}"
            )
            del existing_devices[id_]

    @_handle_preliminary_auth
    async def get_device_state(
        self,
        device_id: str,
        *,
        force: bool = True,
    ) -> Optional[Dict[str, Any]]:
        _LOGGER.debug(f"[{self}] Fetching state for device {device_id}")
        request_tag = f"device_state__{device_id}"

        async with (
            await self.prepare_authenticated_request(
                METH_GET,
                self.BASE_URL + "/user/devices",
                params={"device": f"{device_id}_state"},
                request_tag=(None if force else request_tag),
            )
        ) as response:
            if not force and response.status == 304:
                _LOGGER.debug(f"[{self}] Device data not modified, no updates")
                return

            response_tag = response.headers.get(ETAG)

            try:
                device_data_list = await response.json()
            except (ContentTypeError, JSONDecodeError) as exc:
                raise TurkovAPIError(
                    f"[{self}] Error decoding json data: {await response.text()}"
                ) from exc

        # Process device data
        try:
            if not isinstance(device_data_list, List):
                raise TurkovAPIError("Improper device data format")

            try:
                device_data_text = device_data_list[-1]
            except IndexError as exc:
                raise TurkovAPIError("Missing device data") from exc

            try:
                device_data = loads(device_data_text)
            except JSONDecodeError as exc:
                raise TurkovAPIError("Improper device data encoding") from exc

            if not isinstance(device_data, dict):
                raise TurkovAPIError("Improper device data format")
        except Exception:
            _LOGGER.error(
                f"[{self}] Failed to fetch state for device {device_id}: {device_data_list}"
            )
            raise

        if response_tag:
            self._request_history[request_tag] = response_tag

        _LOGGER.debug(
            f"[{self}] Fetching state for device {device_id} successful: {device_data}"
        )
        return device_data

    @_handle_preliminary_auth
    async def set_device_value(
        self, device_id: str, key: str, value: Any
    ) -> None:
        _LOGGER.debug(
            f"[{self}] Sending `{key}`=`{value}` (type: {type(value)}) to device {device_id}"
        )

        async with (
            await self.prepare_authenticated_request(
                METH_POST,
                f"{self.BASE_URL}/user/device/{device_id}",
                json={key: value},
            )
        ) as response:
            try:
                message = (await response.json())["message"]
            except (ContentTypeError, JSONDecodeError) as exc:
                raise TurkovAPIError(
                    f"[{self}] Error decoding json data: {await response.text()}"
                ) from exc
            except (LookupError, ValueError, TypeError, AttributeError) as exc:
                raise TurkovAPIError(
                    f"[{self}] Response contains no message: {await response.text()}"
                ) from exc

        if message != "success":
            raise TurkovAPIError(f"[{self}] Error calling setter: {message}")

        _LOGGER.debug(
            f"[{self}] Setting `{key}`=`{value}` to device {device_id} successful"
        )


class TurkovDevice:
    @staticmethod
    def extract_image_url(image_id: Any):
        pass

    IMAGES_BY_DEVICE_TYPE: ClassVar[Mapping[str, str]] = {
        "Zenit": "/images/zenit.jpg",
        "Capsule": "/images/capsule.jpg",
        "i-Vent": "/images/ivent.jpg",
    }

    @staticmethod
    def _float_less(x):
        return float(x) / 10

    ATTRIBUTE_KEY_MAPPING: ClassVar[
        Mapping[str, Tuple[str, Optional[Callable[[Any], Any]]]]
    ] = {
        "is_on": ("on", None),
        "fan_speed": ("fan_speed", str),
        "fan_mode": ("fan_mode", None),
        "target_temperature": ("temp_sp", float),
        "selected_mode": ("mode", str),
        "setup": ("setup", str),
        "filter_life_percentage": ("filter", float),
        "outdoor_temperature": ("out_temp", _float_less),
        "indoor_temperature": ("in_temp", _float_less),
        "image_url": ("image", False),
        "indoor_humidity": ("in_humid", _float_less),
        "exhaust_temperature": ("exh_temp", _float_less),
        "air_pressure": ("air_pres", float),
        "co2_level": ("CO2_level", float),
        "current_temperature": ("temp_curr", _float_less),
        "current_humidity": ("hum_curr", _float_less),
        "target_humidity": ("hum_sp", int),
        "fireplace": ("firep", bool),
        "humidifier": ("humib", bool),
        "first_relay": ("relay_1", bool),
        "first_relay_name": ("relay_1_name", str),
        "second_relay": ("relay_2", bool),
        "second_relay_name": ("relay_2_name", str),
    }

    def __str__(self) -> str:
        """Convert object to string."""
        return f"{self.__class__.__name__}[{_log_hide_id(self._id)}]"

    def __repr__(self) -> str:
        """Represent object attributes with a string value."""
        return (
            f"<{self.__class__.__name__}"
            f"[id={self._id}, "
            f"{', '.join(k + '=' + str(getattr(self, k)) for k in self.ATTRIBUTE_KEY_MAPPING)}]>"
        )

    # noinspection PyShadowingBuiltins
    def __init__(
        self,
        id: Optional[str] = None,
        api: Optional[TurkovAPI] = None,
        session: Optional[aiohttp.ClientSession] = None,
        host: Optional[str] = None,
        port: int = 80,
        *,
        serial_number: Optional[str] = None,
        pin: Optional[str] = None,
        type: Optional[str] = None,
        name: Optional[str] = None,
        firmware_version: Optional[str] = None,
        image_url: Optional[str] = None,
    ) -> None:
        """
        Initialise Turkov device object.

        :param id:
        :param api:
        :param serial_number:
        :param pin:
        :param type:
        :param name:
        :param firmware_version:
        :param image_url:
        """
        if api and not id:
            raise ValueError("id cannot be empty with api")
        if not (api or session):
            raise ValueError(
                "object must be provided with at least api or session"
            )

        # Required attributes
        self._api = api
        self._id = id
        self._session = session
        self.host = host
        self._port = port

        # Optional attributes
        self.serial_number = serial_number
        self.pin = pin
        self.type = type
        self.name = name
        self.firmware_version = firmware_version
        self.image_url = image_url

        # Placeholders
        self.error: Optional[str] = None
        self.is_on: Optional[bool] = None
        self.fan_speed: Optional[str] = None
        self.fan_mode: Optional[str] = None
        self.target_temperature: Optional[float] = None
        # self.current_mode: Optional[str] = None
        self.selected_mode: Optional[str] = None
        self.filter_life_percentage: Optional[float] = None
        self.outdoor_temperature: Optional[float] = None
        self.indoor_temperature: Optional[float] = None
        self.setup: Optional[str] = None
        self.air_pressure: Optional[float] = None
        self.indoor_humidity: Optional[float] = None
        self.exhaust_temperature: Optional[float] = None
        self.co2_level: Optional[float] = None
        self.current_temperature: Optional[float] = None
        self.current_humidity: Optional[float] = None
        self.target_humidity: Optional[float] = None
        self.fireplace: Optional[bool] = None
        self.humidifier: Optional[bool] = None
        self.first_relay: Optional[bool] = None
        self.first_relay_name: Optional[str] = None
        self.second_relay: Optional[bool] = None
        self.second_relay_name: Optional[str] = None

    @property
    def id(self) -> Optional[str]:
        return self._id

    @property
    def api(self) -> Optional[TurkovAPI]:
        return self._api

    @property
    def session(self) -> aiohttp.ClientSession:
        """Return usable session object"""
        if self._session:
            return self._session
        if self._api:
            return self._api.session
        raise RuntimeError("session object missing from device object")

    @property
    def base_url(self) -> str:
        if (host := self.host) is None:
            raise RuntimeError("host not set")
        # noinspection HttpUrlsUsage
        return f"http://{host}:{self.port}"

    @property
    def port(self) -> int:
        """Return preset port"""
        return self._port

    @port.setter
    def port(self, value: int) -> None:
        """Validate and set new port value"""
        if not (0 < value < 65536):
            raise ValueError("port must be within [1:65535] range")
        self._port = value

    async def get_state_local(self) -> Dict[str, Any]:
        if not self.host:
            raise RuntimeError("host not set")

        request_url = self.base_url + "/state"
        _LOGGER.debug(f"[{self}] Requesting state locally from: {request_url}")
        async with self.session.get(request_url) as response:
            data = await response.json(content_type=None)
            _LOGGER.debug(f"[{self}] Received local state data: {data}")
            return data

    async def get_state(
        self, *, force: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Get device state attributes.
        :param force: Bypass request caching (on by default)
        :return: Dictionary of attributes to be mapped onto device.
        """
        if self.host:
            try:
                return await self.get_state_local()
            except (
                aiohttp.ClientError,
                TimeoutError,
                JSONDecodeError,
            ):
                if not self._api:
                    raise
                _LOGGER.warning(
                    f"[{self}] Local fetching failed, attempting to fetch state from cloud"
                )

        if self._api:
            return await self._api.get_device_state(self._id, force=force)

        raise TurkovAPIError("No method to fetch device state")

    async def set_value_local(self, key: str, value: Any) -> None:
        if not self.host:
            raise RuntimeError("host not set")

        request_url = self.base_url + "/command"
        _LOGGER.debug(f"[{self}] Sending `{key}`=`{value}` (type: {type(value)}) to endpoint {request_url}")
        async with self.session.post(
            self.base_url + "/command", data="{" + key + ": \"" + str(value) + "\"}"
        ) as response:
            data = await response.json(content_type=None)
            _LOGGER.debug(f"[{self}] Received local command result: {data}")
            return data

    async def set_value(self, key: str, value: Any) -> None:
        """
        Set device attribute.

        :param key:
        :param value:
        :return:
        """
        if self.host:
            try:
                return await self.set_value_local(key, value)
            except asyncio.CancelledError:
                raise
            except (
                aiohttp.ClientError,
                TimeoutError,
                JSONDecodeError,
            ):
                if not self._api:
                    raise
                _LOGGER.warning(
                    f"[{self}] Local command failed, attempting to issue command via cloud"
                )

        if self._api:
            return await self._api.set_device_value(self._id, key, value)

        raise TurkovAPIError("No method to set device values")

    async def update_state(
        self, mark_as_none_if_not_present: bool = False, force: bool = False
    ) -> Set[str]:
        """
        Update state of target device.

        :param mark_as_none_if_not_present: Mark expected attributes as None if not present in response.
        :param force: Bypass request caching (off by default)
        :return: Set of changed attributes (including set to None if `mark_as_none_if_present` is set to True)
        """

        device_data = await self.get_state(force=force)
        changed_attributes = set()

        if device_data is None:
            # Return if nothing is changed
            return changed_attributes

        def set_attribute(attr_: str, value_: Any):
            _LOGGER.debug(f"[{self}] Setting '{attr_}' = '{value_}'")
            setattr(self, attr_, value_)
            changed_attributes.add(attr_)

        # Generic attribute handling process
        for attribute_name, (
            key,
            converter,
        ) in self.ATTRIBUTE_KEY_MAPPING.items():
            if converter is False:
                continue

            try:
                value = device_data[key]
            except KeyError:
                if not mark_as_none_if_not_present:
                    continue
                value = None
            else:
                if callable(converter):
                    value = converter(value)

            if value != getattr(self, attribute_name):
                set_attribute(attribute_name, value)

        # Custom attribute handling process
        base_url = (self._api or TurkovAPI).BASE_URL
        image_url = device_data.get("image") or None
        if image_url and self._id:
            # Custom image detected
            image_url = f"{base_url}/upload/{self._id}_{image_url}.jpg"
        elif self.type in self.IMAGES_BY_DEVICE_TYPE:
            # Select image based on device type
            image_url = self.IMAGES_BY_DEVICE_TYPE[self.type]
            if image_url.startswith("/"):
                image_url = base_url + image_url

        if (
            (image_url is None and self.image_url is not None)
            if mark_as_none_if_not_present
            else (self.image_url != image_url)
        ):
            set_attribute("image_url", image_url)

        # @TODO: this is done for a single 'Capsule' device, review others

        return changed_attributes

    async def toggle_heater(self, turn_on: Optional[bool] = None) -> None:
        if turn_on is None:
            turn_on = not self.is_heater_on

        await (self.turn_on_heater if turn_on else self.turn_off_hvac)()

    async def toggle_cooler(self, turn_on: Optional[bool] = None) -> None:
        if turn_on is None:
            turn_on = not self.is_cooler_on

        await (self.turn_on_cooler if turn_on else self.turn_off_hvac)()

    @property
    def has_heater(self) -> bool:
        return self.setup in ("heating", "both", None)

    @property
    def has_cooler(self) -> bool:
        return self.setup in ("cooling", "both", None)

    @property
    def is_heater_on(self) -> bool:
        return self.selected_mode == "heating"

    @property
    def is_cooler_on(self) -> bool:
        return self.selected_mode == "cooling"

    async def turn_off_hvac(self) -> None:
        await self.set_value("mode", "0")

    async def turn_on_heater(self) -> None:
        # @TODO: might be different depending on model
        await self.set_value("mode", "1")

    async def turn_on_cooler(self) -> None:
        await self.set_value("mode", "2")

    async def toggle(self, turn_on: Optional[bool] = None) -> None:
        """
        Toggle device (flip between on/off states)

        :param turn_on: Optional discrete command.
        """
        if turn_on is None:
            turn_on = self.is_on

        await (self.turn_on if turn_on else self.turn_off)()

    async def turn_on(self) -> None:
        await self.set_value("on", "true")

    async def turn_off(self) -> None:
        await self.set_value("on", "false")

    async def set_fan_speed(self, fan_speed: str) -> None:
        if fan_speed not in ("auto", "0", "1", "2", "3"):
            raise TurkovAPIValueError("valid fan speed not specified")

        await self.set_value("fan_speed", fan_speed)

    async def set_target_temperature(
        self, target_temperature: Union[int, SupportsInt]
    ) -> None:
        target_temperature = int(target_temperature)

        if not (15 <= target_temperature <= 50):
            raise TurkovAPIValueError("target temperature out of bounds")

        await self.set_value("temp_sp", target_temperature)

    async def set_target_humidity(
        self, target_humidity: Union[int, SupportsInt]
    ) -> None:
        target_humidity = int(target_humidity)

        if not (40 <= target_humidity <= 100):
            raise TurkovAPIValueError("target humidity out of bounds")

        await self.set_value("hum_sp", target_humidity)

    async def toggle_fireplace(self, enable: Optional[bool] = None) -> None:
        if enable is None:
            enable = self.fireplace
        await self.set_value("firep", cmd := bool(enable))
        # self.fireplace = cmd

    async def turn_on_fireplace(self) -> None:
        await self.toggle_fireplace(True)

    async def turn_off_fireplace(self) -> None:
        await self.toggle_fireplace(False)

    async def toggle_humidifier(self, enable: Optional[bool] = None) -> None:
        if enable is None:
            enable = self.humidifier
        await self.set_value("humib", cmd := bool(enable))
        # self.humidifier = cmd

    async def turn_on_humidifier(self) -> None:
        await self.toggle_humidifier(True)

    async def turn_off_humidifier(self) -> None:
        await self.toggle_humidifier(False)

    async def toggle_first_relay(self, enable: Optional[bool] = None) -> None:
        if enable is None:
            enable = self.first_relay
        await self.set_value("relay_1", cmd := bool(enable))
        # self.first_relay = cmd

    async def turn_on_first_relay(self) -> None:
        await self.toggle_first_relay(True)

    async def turn_off_first_relay(self) -> None:
        await self.toggle_first_relay(False)

    async def set_first_relay_name(self, name: str) -> None:
        await self.set_value("relay_1_name", name)
        # self.first_relay_name = name

    async def toggle_second_relay(self, enable: Optional[bool] = None) -> None:
        if enable is None:
            enable = self.second_relay
        await self.set_value("relay_2", cmd := bool(enable))
        # self.second_relay = cmd

    async def turn_on_second_relay(self) -> None:
        await self.toggle_second_relay(True)

    async def turn_off_second_relay(self) -> None:
        await self.toggle_second_relay(False)

    async def set_second_relay_name(self, name: str) -> None:
        await self.set_value("relay_2_name", name)
        # self.second_relay_name = name
