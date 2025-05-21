"""Platform for the Turkov sensor component."""

import logging
from dataclasses import dataclass
from functools import partial
import typing

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfTemperature,
    UnitOfPressure,
)
from homeassistant.core import callback

from .entity import TurkovEntity, TurkovEntityDescription
from .helpers import async_setup_entry_for_platform

_LOGGER = logging.getLogger(__name__)


@dataclass
class TurkovSensorEntityDescription(
    TurkovEntityDescription, SensorEntityDescription
):
    """Base class for Turkov sensors."""


# Новый словарь для динамического описания сенсоров
DYNAMIC_SENSOR_TYPES: dict[str, TurkovSensorEntityDescription] = {
    "outdoor_temperature": TurkovSensorEntityDescription(
        key="outdoor_temperature",
        name="Outdoor Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "indoor_temperature": TurkovSensorEntityDescription(
        key="indoor_temperature",
        name="Indoor Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "exhaust_temperature": TurkovSensorEntityDescription(
        key="exhaust_temperature",
        name="Exhaust Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "filter_life_percentage": TurkovSensorEntityDescription(
        key="filter_life_percentage",
        name="Filter Used Percentage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        icon="mdi:air-filter",
    ),
    "air_pressure": TurkovSensorEntityDescription(
        key="air_pressure",
        name="Air Pressure",
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UnitOfPressure.PA,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    "indoor_humidity": TurkovSensorEntityDescription(
        key="indoor_humidity",
        name="Indoor Humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "co2_level": TurkovSensorEntityDescription(
        key="co2_level",
        name="CO2 Level",
        device_class=SensorDeviceClass.CO2,
        native_unit_of_measurement="ppm",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "current_temperature": TurkovSensorEntityDescription(
        key="current_temperature",
        name="Current Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "current_humidity": TurkovSensorEntityDescription(
        key="current_humidity",
        name="Current Humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "fan_speed": TurkovSensorEntityDescription(
        key="fan_speed",
        name="Fan Speed",
        icon="mdi:fan",
    ),
    "fan_mode": TurkovSensorEntityDescription(
        key="fan_mode",
        name="Fan Mode",
        icon="mdi:fan-auto",
    ),
    "target_temperature": TurkovSensorEntityDescription(
        key="target_temperature",
        name="Target Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "target_humidity": TurkovSensorEntityDescription(
        key="target_humidity",
        name="Target Humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "fireplace": TurkovSensorEntityDescription(
        key="fireplace",
        name="Fireplace State",
        icon="mdi:fireplace",
    ),
    "humidifier": TurkovSensorEntityDescription(
        key="humidifier",
        name="Humidifier State",
        icon="mdi:air-humidifier",
    ),
    "first_relay": TurkovSensorEntityDescription(
        key="first_relay",
        name="First Relay State",
        icon="mdi:electric-switch",
    ),
    "second_relay": TurkovSensorEntityDescription(
        key="second_relay",
        name="Second Relay State",
        icon="mdi:electric-switch",
    ),
    # Можно добавить другие сенсоры по аналогии
}

# Оставляем ENTITY_TYPES для обратной совместимости
ENTITY_TYPES: tuple[TurkovSensorEntityDescription, ...] = tuple(DYNAMIC_SENSOR_TYPES.values())


class TurkovSensor(TurkovEntity, SensorEntity):
    """Representation of a Turkov sensor."""

    entity_description: TurkovSensorEntityDescription

    @callback
    def _update_attr(self) -> None:
        """Handle updated data from the coordinator."""
        super()._update_attr()
        if self._attr_available:
            self._attr_native_value = getattr(
                self.coordinator.turkov_device, self.entity_description.key, None
            )


def _get_dynamic_sensor_descriptions(device) -> list[TurkovSensorEntityDescription]:
    """Определяет, какие сенсоры доступны для устройства."""
    available = []
    for key, desc in DYNAMIC_SENSOR_TYPES.items():
        if getattr(device, key, None) is not None:
            available.append(desc)
    return available


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Turkov sensors dynamically."""
    from .const import DOMAIN
    turkov_update_coordinators = hass.data[DOMAIN][entry.entry_id]
    add_entities = []
    for identifier, coordinator in turkov_update_coordinators.items():
        device = coordinator.turkov_device
        for desc in _get_dynamic_sensor_descriptions(device):
            add_entities.append(
                TurkovSensor(
                    turkov_device_coordinator=coordinator,
                    turkov_device_identifier=identifier,
                    entity_description=desc,
                    enabled_default=True,
                )
            )
    if add_entities:
        async_add_entities(add_entities, update_before_add=False)
