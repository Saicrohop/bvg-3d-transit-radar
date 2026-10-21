"""Experimental schedule-only routing over local GTFS transfers/pathways.

This proof of concept uses explicit GTFS transfers and station-internal paths.
It does not route on streets, consume real-time Alerts, geocode addresses, or
filter pathways for mobility/accessibility needs. Results always carry an
operation uncertainty warning and stay off public APIs.
"""

from __future__ import annotations

import csv
from array import array
from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from heapq import heappop, heappush
from pathlib import Path
from typing import Iterator

OPERATION_UNCONFIRMED_MESSAGE = (
    "Há previsão de passagem, mas não conseguimos confirmar se o serviço está operando."
)
MAX_JOURNEY_RESULTS = 100
_WEEKDAY_FIELDS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


class LocalGtfsDataError(ValueError):
    """The local static GTFS files are not safe to use for schedule lookup."""


class UnsupportedStopLocation(ValueError):
    """The prototype requires a boardable platform stop, not a station/entrance."""


@dataclass(frozen=True, slots=True)
class DirectScheduledJourney:
    origin_stop_id: str
    origin_stop_name: str
    destination_stop_id: str
    destination_stop_name: str
    trip_id: str
    route_id: str
    route_short_name: str | None
    trip_headsign: str | None
    direction_id: int | None
    service_date: date
    departure_time: str
    arrival_time: str
    duration_seconds: int
    operation_confirmed: bool = False
    operation_message: str = OPERATION_UNCONFIRMED_MESSAGE


@dataclass(frozen=True, slots=True)
class ScheduledLeg:
    trip_id: str
    route_id: str
    route_short_name: str | None
    trip_headsign: str | None
    from_stop_id: str
    from_stop_name: str
    to_stop_id: str
    to_stop_name: str
    departure_time: str
    arrival_time: str
    duration_seconds: int


@dataclass(frozen=True, slots=True)
class ScheduledTransfer:
    from_stop_id: str
    from_stop_name: str
    to_stop_id: str
    to_stop_name: str
    transfer_type: int | None
    min_transfer_time_seconds: int | None
    scheduled_gap_seconds: int
    pathway_traversal_seconds: int | None = None
    pathway_stop_ids: tuple[str, ...] = ()
    pathway_ids: tuple[str, ...] = ()
    pathway_modes: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class ScheduledJourney:
    service_date: date
    legs: tuple[ScheduledLeg, ...]
    transfers: tuple[ScheduledTransfer, ...]
    duration_seconds: int
    operation_confirmed: bool = False
    operation_message: str = OPERATION_UNCONFIRMED_MESSAGE

    @property
    def departure_time(self) -> str:
        return self.legs[0].departure_time

    @property
    def arrival_time(self) -> str:
        return self.legs[-1].arrival_time


@dataclass(frozen=True, slots=True)
class _CalendarRule:
    start_date: date
    end_date: date
    weekdays: tuple[bool, ...]


@dataclass(frozen=True, slots=True)
class _Trip:
    trip_id: str
    route_id: str
    service_id: str
    headsign: str | None
    direction_id: int | None


@dataclass(frozen=True, slots=True)
class _Stop:
    stop_id: str
    name: str
    location_type: int
    parent_station: str | None
    stop_access: int | None


@dataclass(frozen=True, slots=True)
class _TransferRule:
    from_stop_id: str
    to_stop_id: str
    transfer_type: int
    min_transfer_time_seconds: int | None
    from_route_id: str | None
    to_route_id: str | None
    from_trip_id: str | None
    to_trip_id: str | None
    specificity: int


@dataclass(frozen=True, slots=True)
class _PathwayEdge:
    to_stop_id: str
    pathway_id: str
    pathway_mode: int
    traversal_seconds: int


@dataclass(frozen=True, slots=True)
class _PathwayPath:
    traversal_seconds: int
    stop_ids: tuple[str, ...]
    pathway_ids: tuple[str, ...]
    pathway_modes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _TransferInfo:
    rule: _TransferRule | None
    pathway: _PathwayPath | None


@dataclass(frozen=True, slots=True)
class _SearchLabel:
    trip_index: int
    position: int
    parent_label_id: int | None
    board_position: int
    transfer_from_parent: _TransferInfo | None
    transfer_count: int
    origin_departure_seconds: int


class _TripTimeColumns:
    """Flat event columns ordered by trip, then stop_sequence."""

    __slots__ = (
        "stop_indexes",
        "sequences",
        "arrival_seconds",
        "departure_seconds",
        "pickup_types",
        "drop_off_types",
        "trip_offsets",
    )

    def __init__(self, trip_offsets: list[int]) -> None:
        self.stop_indexes = array("I")
        self.sequences = array("I")
        self.arrival_seconds = array("I")
        self.departure_seconds = array("I")
        self.pickup_types = array("I")
        self.drop_off_types = array("I")
        self.trip_offsets = array("I", trip_offsets)


class _StopTimeColumns:
    """Compact per-stop index over stop_times; columns use unsigned integers."""

    __slots__ = (
        "trip_indexes",
        "event_indexes",
        "sequences",
        "arrival_seconds",
        "departure_seconds",
        "pickup_types",
        "drop_off_types",
        "departure_order",
    )

    def __init__(self) -> None:
        self.trip_indexes = array("I")
        self.event_indexes = array("I")
        self.sequences = array("I")
        self.arrival_seconds = array("I")
        self.departure_seconds = array("I")
        self.pickup_types = array("I")
        self.drop_off_types = array("I")
        self.departure_order = array("I")

    def append(
        self,
        *,
        trip_index: int,
        event_index: int,
        sequence: int,
        arrival_seconds: int,
        departure_seconds: int,
        pickup_type: int,
        drop_off_type: int,
    ) -> None:
        self.trip_indexes.append(trip_index)
        self.event_indexes.append(event_index)
        self.sequences.append(sequence)
        self.arrival_seconds.append(arrival_seconds)
        self.departure_seconds.append(departure_seconds)
        self.pickup_types.append(pickup_type)
        self.drop_off_types.append(drop_off_type)

    def sort_by_departure(self) -> None:
        self.departure_order = array(
            "I",
            sorted(range(len(self.departure_seconds)), key=self.departure_seconds.__getitem__),
        )


def _format_gtfs_time(value_seconds: int) -> str:
    hours, remainder = divmod(value_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def parse_gtfs_time(value: str) -> int:
    """Parse GTFS HH:MM:SS as seconds from the service-day start, allowing >24h."""
    if not isinstance(value, str):
        raise LocalGtfsDataError("GTFS time must be text")
    parts = value.split(":")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise LocalGtfsDataError("GTFS time must use HH:MM:SS")
    hours, minutes, seconds = (int(part) for part in parts)
    if len(parts[0]) > 3 or not 0 <= minutes < 60 or not 0 <= seconds < 60:
        raise LocalGtfsDataError("GTFS time is outside the supported range")
    return hours * 3600 + minutes * 60 + seconds


def _parse_gtfs_date(value: str, *, filename: str) -> date:
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except (TypeError, ValueError) as error:
        raise LocalGtfsDataError(f"Invalid date in {filename}") from error


def _read_rows(
    directory: Path,
    filename: str,
    required_columns: tuple[str, ...],
) -> Iterator[dict[str, str]]:
    path = directory / filename
    try:
        stream = path.open(encoding="utf-8-sig", newline="")
    except OSError as error:
        raise LocalGtfsDataError(f"Cannot open required GTFS file: {filename}") from error

    with stream:
        try:
            reader = csv.DictReader(stream, strict=True)
            fields = reader.fieldnames or []
            missing = [column for column in required_columns if column not in fields]
            if missing:
                raise LocalGtfsDataError(
                    f"GTFS file {filename} is missing required columns"
                )
            for row in reader:
                yield row
        except (UnicodeError, csv.Error) as error:
            raise LocalGtfsDataError(f"Cannot parse GTFS file: {filename}") from error


def _optional_integer(value: str | None, *, field: str, filename: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError as error:
        raise LocalGtfsDataError(f"Invalid {field} in {filename}") from error


def _optional_text(value: str | None) -> str | None:
    return value if value else None


def _transfer_specificity(
    from_trip_id: str | None,
    to_trip_id: str | None,
    from_route_id: str | None,
    to_route_id: str | None,
) -> int:
    from_kind = 2 if from_trip_id else 1 if from_route_id else 0
    to_kind = 2 if to_trip_id else 1 if to_route_id else 0
    if from_kind == to_kind == 2:
        return 1
    if {from_kind, to_kind} == {1, 2}:
        return 2
    if 2 in (from_kind, to_kind):
        return 3
    if from_kind == to_kind == 1:
        return 4
    if 1 in (from_kind, to_kind):
        return 5
    return 6


class LocalGtfsSchedulePlanner:
    """Find schedule-only journeys over platform stops and explicit connections.

    Transfers require a matching GTFS rule or a timed station pathway. The
    prototype does not infer street walking or normal operation and is not a
    passenger-facing production API.
    """

    def __init__(self, gtfs_directory: Path) -> None:
        self._directory = Path(gtfs_directory)
        self._routes = self._load_routes()
        self._stops = self._load_stops()
        self._stops_by_index = tuple(self._stops.values())
        self._stop_index_by_id = {
            stop.stop_id: index for index, stop in enumerate(self._stops_by_index)
        }
        self._station_platforms_by_id: dict[str, list[str]] = defaultdict(list)
        for stop in self._stops.values():
            if stop.parent_station and stop.location_type == 0:
                self._station_platforms_by_id[stop.parent_station].append(stop.stop_id)
        self._calendar = self._load_calendar()
        self._exceptions = self._load_calendar_exceptions()
        self._trips = self._load_trips()
        self._validate_trip_services()
        self._trips_by_index = tuple(self._trips.values())
        self._trip_index_by_id = {
            trip.trip_id: index for index, trip in enumerate(self._trips_by_index)
        }
        self._stop_time_index: dict[str, _StopTimeColumns] | None = None
        self._trip_time_index: _TripTimeColumns | None = None
        self._transfer_rules_by_pair = self._load_transfers()
        transfer_rules_by_from: dict[
            str, list[tuple[str, tuple[_TransferRule, ...]]]
        ] = defaultdict(list)
        for (from_stop_id, to_stop_id), rules in self._transfer_rules_by_pair.items():
            transfer_rules_by_from[from_stop_id].append((to_stop_id, rules))
        self._transfer_rules_by_from = {
            from_stop_id: tuple(sorted(edges, key=lambda edge: edge[0]))
            for from_stop_id, edges in transfer_rules_by_from.items()
        }
        self._pathways_by_from = self._load_pathways()
        self._pathway_transfer_cache: dict[str, dict[str, _PathwayPath]] = {}


    def find_direct_journeys(
        self,
        *,
        origin_stop_id: str,
        destination_stop_id: str,
        service_date: date,
        departure_after: str,
        limit: int = 5,
    ) -> tuple[DirectScheduledJourney, ...]:
        """Return scheduled trips that serve both selected stops in order."""
        if not isinstance(origin_stop_id, str) or not origin_stop_id.strip():
            raise ValueError("origin_stop_id must be non-empty text")
        if not isinstance(destination_stop_id, str) or not destination_stop_id.strip():
            raise ValueError("destination_stop_id must be non-empty text")
        if type(service_date) is not date:
            raise ValueError("service_date must be a date, not a datetime")
        if type(limit) is not int or not 1 <= limit <= MAX_JOURNEY_RESULTS:
            raise ValueError(f"limit must be between 1 and {MAX_JOURNEY_RESULTS}")
        departure_after_seconds = parse_gtfs_time(departure_after)
        origin = self._boardable_stop(origin_stop_id)
        destination = self._boardable_stop(destination_stop_id)
        if origin_stop_id == destination_stop_id:
            return ()

        active_services = self._active_service_ids(service_date)
        active_trip_indexes = {
            index
            for index, trip in enumerate(self._trips_by_index)
            if trip.service_id in active_services
        }
        if not active_trip_indexes:
            return ()

        if self._stop_time_index is None:
            self._stop_time_index = self._load_stop_time_index()
        origin_events = self._stop_time_index.get(origin_stop_id)
        destination_events = self._stop_time_index.get(destination_stop_id)
        if origin_events is None or destination_events is None:
            return ()

        destination_by_trip: dict[int, list[tuple[int, int, int]]] = defaultdict(list)
        for index, trip_index in enumerate(destination_events.trip_indexes):
            if trip_index in active_trip_indexes:
                destination_by_trip[trip_index].append(
                    (
                        destination_events.sequences[index],
                        destination_events.arrival_seconds[index],
                        destination_events.drop_off_types[index],
                    )
                )
        for events in destination_by_trip.values():
            events.sort(key=lambda event: event[0])

        origin_by_trip: dict[int, list[tuple[int, int]]] = defaultdict(list)
        for index, trip_index in enumerate(origin_events.trip_indexes):
            departure_seconds = origin_events.departure_seconds[index]
            if (
                trip_index in active_trip_indexes
                and departure_seconds >= departure_after_seconds
                and origin_events.pickup_types[index] == 0
            ):
                origin_by_trip[trip_index].append(
                    (origin_events.sequences[index], departure_seconds)
                )

        journeys: list[DirectScheduledJourney] = []
        for trip_index, origin_events_for_trip in origin_by_trip.items():
            best_journey: tuple[int, int, int, int] | None = None
            for origin_sequence, departure_seconds in origin_events_for_trip:
                for destination_sequence, arrival_seconds, drop_off_type in (
                    destination_by_trip.get(trip_index, ())
                ):
                    if (
                        destination_sequence <= origin_sequence
                        or arrival_seconds < departure_seconds
                        or drop_off_type != 0
                    ):
                        continue
                    candidate = (
                        arrival_seconds,
                        departure_seconds,
                        destination_sequence,
                        origin_sequence,
                    )
                    if best_journey is None or candidate < best_journey:
                        best_journey = candidate
            if best_journey is None:
                continue
            arrival_seconds, departure_seconds = best_journey[:2]
            trip = self._trips_by_index[trip_index]
            journeys.append(
                DirectScheduledJourney(
                    origin_stop_id=origin.stop_id,
                    origin_stop_name=origin.name,
                    destination_stop_id=destination.stop_id,
                    destination_stop_name=destination.name,
                    trip_id=trip.trip_id,
                    route_id=trip.route_id,
                    route_short_name=self._routes[trip.route_id],
                    trip_headsign=trip.headsign,
                    direction_id=trip.direction_id,
                    service_date=service_date,
                    departure_time=_format_gtfs_time(departure_seconds),
                    arrival_time=_format_gtfs_time(arrival_seconds),
                    duration_seconds=arrival_seconds - departure_seconds,
                )
            )

        return tuple(
            sorted(
                journeys,
                key=lambda journey: (
                    parse_gtfs_time(journey.departure_time),
                    parse_gtfs_time(journey.arrival_time),
                    journey.route_id,
                    journey.trip_id,
                ),
            )[:limit]
        )

    def find_earliest_journey(
        self,
        *,
        origin_stop_id: str,
        destination_stop_id: str,
        service_date: date,
        departure_after: str,
    ) -> ScheduledJourney | None:
        """Find the earliest schedule-only route using explicit transfer rules."""
        if not isinstance(origin_stop_id, str) or not origin_stop_id.strip():
            raise ValueError("origin_stop_id must be non-empty text")
        if not isinstance(destination_stop_id, str) or not destination_stop_id.strip():
            raise ValueError("destination_stop_id must be non-empty text")
        if type(service_date) is not date:
            raise ValueError("service_date must be a date, not a datetime")
        departure_after_seconds = parse_gtfs_time(departure_after)
        origin = self._boardable_stop(origin_stop_id)
        destination = self._boardable_stop(destination_stop_id)
        if origin_stop_id == destination_stop_id:
            return None

        active_services = self._active_service_ids(service_date)
        active_trip_indexes = {
            index
            for index, trip in enumerate(self._trips_by_index)
            if trip.service_id in active_services
        }
        if not active_trip_indexes:
            return None

        if self._stop_time_index is None:
            self._stop_time_index = self._load_stop_time_index()
        trip_events = self._trip_time_index
        if trip_events is None:
            raise LocalGtfsDataError("The local stop-time index was not initialized")
        origin_events = self._stop_time_index.get(origin_stop_id)
        if origin_events is None:
            return None

        labels: list[_SearchLabel] = []
        best_label_by_state: dict[tuple[int, int], int] = {}
        queue: list[tuple[int, int, int, int, int, int]] = []
        first_origin_row = bisect_left(
            origin_events.departure_order,
            departure_after_seconds,
            key=origin_events.departure_seconds.__getitem__,
        )
        for ordered_position in range(first_origin_row, len(origin_events.departure_order)):
            row_index = origin_events.departure_order[ordered_position]
            trip_index = origin_events.trip_indexes[row_index]
            event_index = origin_events.event_indexes[row_index]
            if (
                trip_index not in active_trip_indexes
                or origin_events.pickup_types[row_index] != 0
            ):
                continue
            position = event_index - trip_events.trip_offsets[trip_index]
            next_position = position + 1
            if next_position >= (
                trip_events.trip_offsets[trip_index + 1]
                - trip_events.trip_offsets[trip_index]
            ):
                continue
            next_event = event_index + 1
            departure_seconds = origin_events.departure_seconds[row_index]
            if trip_events.arrival_seconds[next_event] < departure_seconds:
                continue
            self._enqueue_search_label(
                _SearchLabel(
                    trip_index=trip_index,
                    position=next_position,
                    parent_label_id=None,
                    board_position=position,
                    transfer_from_parent=None,
                    transfer_count=0,
                    origin_departure_seconds=departure_seconds,
                ),
                labels,
                best_label_by_state,
                queue,
            )

        while queue:
            _, _, _, _, _, label_id = heappop(queue)
            label = labels[label_id]
            state = (label.trip_index, label.position)
            if best_label_by_state.get(state) != label_id:
                continue
            event_index = trip_events.trip_offsets[label.trip_index] + label.position
            current_arrival = trip_events.arrival_seconds[event_index]
            current_stop_index = trip_events.stop_indexes[event_index]
            current_stop = self._stops_by_index[current_stop_index]
            if (
                current_stop.stop_id == destination_stop_id
                and trip_events.drop_off_types[event_index] == 0
            ):
                return self._journey_from_search_labels(
                    label_id,
                    labels,
                    service_date,
                )

            next_position = label.position + 1
            if next_position < (
                trip_events.trip_offsets[label.trip_index + 1]
                - trip_events.trip_offsets[label.trip_index]
            ):
                next_event = event_index + 1
                current_departure = trip_events.departure_seconds[event_index]
                if trip_events.arrival_seconds[next_event] >= current_departure:
                    self._enqueue_search_label(
                        _SearchLabel(
                            trip_index=label.trip_index,
                            position=next_position,
                            parent_label_id=label_id,
                            board_position=label.board_position,
                            transfer_from_parent=None,
                            transfer_count=label.transfer_count,
                            origin_departure_seconds=label.origin_departure_seconds,
                        ),
                        labels,
                        best_label_by_state,
                        queue,
                    )

            if trip_events.drop_off_types[event_index] != 0:
                continue
            transfer_options = self._transfer_options_from(current_stop.stop_id)
            for to_stop_id, rules, pathway in transfer_options:
                target_events = self._stop_time_index.get(to_stop_id)
                if target_events is None:
                    continue
                first_departure = bisect_left(
                    target_events.departure_order,
                    current_arrival,
                    key=target_events.departure_seconds.__getitem__,
                )
                for ordered_position in range(
                    first_departure,
                    len(target_events.departure_order),
                ):
                    row_index = target_events.departure_order[ordered_position]
                    next_trip_index = target_events.trip_indexes[row_index]
                    if (
                        next_trip_index not in active_trip_indexes
                        or next_trip_index == label.trip_index
                        or target_events.pickup_types[row_index] != 0
                    ):
                        continue
                    next_trip = self._trips_by_index[next_trip_index]
                    current_trip = self._trips_by_index[label.trip_index]
                    transfer_rule = self._select_transfer_rule(
                        rules,
                        current_trip,
                        next_trip,
                    ) if rules else None
                    if transfer_rule is None and pathway is None:
                        continue
                    if transfer_rule is not None and transfer_rule.transfer_type in (3, 4, 5):
                        continue
                    if (
                        transfer_rule is not None
                        and transfer_rule.transfer_type == 0
                        and pathway is None
                    ):
                        continue
                    rule_minimum = (
                        transfer_rule.min_transfer_time_seconds or 0
                        if transfer_rule is not None
                        else 0
                    )
                    pathway_seconds = (
                        pathway.traversal_seconds if pathway is not None else 0
                    )
                    # The transfer minimum covers the connection as a whole;
                    # do not add the same in-station traversal a second time.
                    minimum_seconds = max(rule_minimum, pathway_seconds)
                    departure_seconds = target_events.departure_seconds[row_index]
                    if departure_seconds - current_arrival < minimum_seconds:
                        continue

                    board_event = target_events.event_indexes[row_index]
                    next_position = board_event - trip_events.trip_offsets[next_trip_index] + 1
                    trip_length = (
                        trip_events.trip_offsets[next_trip_index + 1]
                        - trip_events.trip_offsets[next_trip_index]
                    )
                    if next_position >= trip_length:
                        continue
                    next_event = board_event + 1
                    if trip_events.arrival_seconds[next_event] < departure_seconds:
                        continue
                    self._enqueue_search_label(
                        _SearchLabel(
                            trip_index=next_trip_index,
                            position=next_position,
                            parent_label_id=label_id,
                            board_position=board_event
                            - trip_events.trip_offsets[next_trip_index],
                            transfer_from_parent=_TransferInfo(transfer_rule, pathway),
                            transfer_count=label.transfer_count + 1,
                            origin_departure_seconds=label.origin_departure_seconds,
                        ),
                        labels,
                        best_label_by_state,
                        queue,
                    )
        return None

    def _enqueue_search_label(
        self,
        label: _SearchLabel,
        labels: list[_SearchLabel],
        best_label_by_state: dict[tuple[int, int], int],
        queue: list[tuple[int, int, int, int, int, int]],
    ) -> None:
        trip_events = self._trip_time_index
        if trip_events is None:
            raise LocalGtfsDataError("The local stop-time index was not initialized")
        state = (label.trip_index, label.position)
        existing_id = best_label_by_state.get(state)
        candidate_cost = (label.transfer_count, -label.origin_departure_seconds)
        if existing_id is not None:
            existing = labels[existing_id]
            existing_cost = (
                existing.transfer_count,
                -existing.origin_departure_seconds,
            )
            if candidate_cost >= existing_cost:
                return
        label_id = len(labels)
        labels.append(label)
        best_label_by_state[state] = label_id
        event_index = trip_events.trip_offsets[label.trip_index] + label.position
        heappush(
            queue,
            (
                trip_events.arrival_seconds[event_index],
                label.transfer_count,
                -label.origin_departure_seconds,
                label.trip_index,
                label.position,
                label_id,
            ),
        )

    def _select_transfer_rule(
        self,
        rules: tuple[_TransferRule, ...],
        from_trip: _Trip,
        to_trip: _Trip,
    ) -> _TransferRule | None:
        applicable = [
            rule
            for rule in rules
            if (rule.from_trip_id is None or rule.from_trip_id == from_trip.trip_id)
            and (rule.to_trip_id is None or rule.to_trip_id == to_trip.trip_id)
            and (rule.from_route_id is None or rule.from_route_id == from_trip.route_id)
            and (rule.to_route_id is None or rule.to_route_id == to_trip.route_id)
        ]
        if not applicable:
            return None
        best_specificity = min(rule.specificity for rule in applicable)
        best_rules = [
            rule for rule in applicable if rule.specificity == best_specificity
        ]
        if len(best_rules) != 1:
            raise LocalGtfsDataError("Ambiguous highest-specificity transfer rules")
        return best_rules[0]

    def _journey_from_search_labels(
        self,
        final_label_id: int,
        labels: list[_SearchLabel],
        service_date: date,
    ) -> ScheduledJourney:
        label_chain = []
        label_id: int | None = final_label_id
        while label_id is not None:
            label = labels[label_id]
            label_chain.append(label)
            label_id = label.parent_label_id
        label_chain.reverse()

        trip_events = self._trip_time_index
        if trip_events is None:
            raise LocalGtfsDataError("The local stop-time index was not initialized")
        legs: list[ScheduledLeg] = []
        transfers: list[ScheduledTransfer] = []
        current_trip_index = label_chain[0].trip_index
        current_board_position = label_chain[0].board_position
        current_end_position = label_chain[0].position

        for index, label in enumerate(label_chain[1:], start=1):
            if label.trip_index == current_trip_index:
                current_end_position = label.position
                continue

            leg = self._make_scheduled_leg(
                current_trip_index,
                current_board_position,
                current_end_position,
            )
            legs.append(leg)
            transfer_info = label.transfer_from_parent
            if transfer_info is None:
                raise LocalGtfsDataError("Transfer itinerary is missing its edge")
            rule = transfer_info.rule
            pathway = transfer_info.pathway
            previous_event = (
                trip_events.trip_offsets[current_trip_index] + current_end_position
            )
            next_board_event = (
                trip_events.trip_offsets[label.trip_index] + label.board_position
            )
            from_stop = self._stops_by_index[trip_events.stop_indexes[previous_event]]
            to_stop = self._stops_by_index[trip_events.stop_indexes[next_board_event]]
            transfers.append(
                ScheduledTransfer(
                    from_stop_id=from_stop.stop_id,
                    from_stop_name=from_stop.name,
                    to_stop_id=to_stop.stop_id,
                    to_stop_name=to_stop.name,
                    transfer_type=rule.transfer_type if rule is not None else None,
                    min_transfer_time_seconds=(
                        rule.min_transfer_time_seconds if rule is not None else None
                    ),
                    scheduled_gap_seconds=(
                        trip_events.departure_seconds[next_board_event]
                        - trip_events.arrival_seconds[previous_event]
                    ),
                    pathway_traversal_seconds=(
                        pathway.traversal_seconds if pathway is not None else None
                    ),
                    pathway_stop_ids=(pathway.stop_ids if pathway is not None else ()),
                    pathway_ids=(pathway.pathway_ids if pathway is not None else ()),
                    pathway_modes=(pathway.pathway_modes if pathway is not None else ()),
                )
            )
            current_trip_index = label.trip_index
            current_board_position = label.board_position
            current_end_position = label.position

        legs.append(
            self._make_scheduled_leg(
                current_trip_index,
                current_board_position,
                current_end_position,
            )
        )
        return ScheduledJourney(
            service_date=service_date,
            legs=tuple(legs),
            transfers=tuple(transfers),
            duration_seconds=(
                parse_gtfs_time(legs[-1].arrival_time)
                - parse_gtfs_time(legs[0].departure_time)
            ),
        )

    def _make_scheduled_leg(
        self,
        trip_index: int,
        board_position: int,
        end_position: int,
    ) -> ScheduledLeg:
        trip_events = self._trip_time_index
        if trip_events is None:
            raise LocalGtfsDataError("The local stop-time index was not initialized")
        offset = trip_events.trip_offsets[trip_index]
        board_event = offset + board_position
        end_event = offset + end_position
        trip = self._trips_by_index[trip_index]
        from_stop = self._stops_by_index[trip_events.stop_indexes[board_event]]
        to_stop = self._stops_by_index[trip_events.stop_indexes[end_event]]
        departure_seconds = trip_events.departure_seconds[board_event]
        arrival_seconds = trip_events.arrival_seconds[end_event]
        return ScheduledLeg(
            trip_id=trip.trip_id,
            route_id=trip.route_id,
            route_short_name=self._routes[trip.route_id],
            trip_headsign=trip.headsign,
            from_stop_id=from_stop.stop_id,
            from_stop_name=from_stop.name,
            to_stop_id=to_stop.stop_id,
            to_stop_name=to_stop.name,
            departure_time=_format_gtfs_time(departure_seconds),
            arrival_time=_format_gtfs_time(arrival_seconds),
            duration_seconds=arrival_seconds - departure_seconds,
        )

    def _load_stop_time_index(self) -> dict[str, _StopTimeColumns]:
        index: dict[str, _StopTimeColumns] = {}
        trip_events = _TripTimeColumns([0] * (len(self._trips_by_index) + 1))
        current_trip_index = -1
        last_sequence = -1
        event_count = 0
        for row in _read_rows(
            self._directory,
            "stop_times.txt",
            ("trip_id", "stop_id", "stop_sequence", "arrival_time", "departure_time"),
        ):
            trip_id = row.get("trip_id", "")
            trip_index = self._trip_index_by_id.get(trip_id)
            if trip_index is None:
                raise LocalGtfsDataError("stop_times.txt references an unknown trip_id")
            if trip_index < current_trip_index:
                raise LocalGtfsDataError(
                    "stop_times.txt must be grouped in trips.txt order for this prototype"
                )
            if trip_index > current_trip_index:
                for offset_index in range(current_trip_index + 1, trip_index + 1):
                    trip_events.trip_offsets[offset_index] = event_count
                current_trip_index = trip_index
                last_sequence = -1
            stop_id = row.get("stop_id", "")
            if stop_id not in self._stops:
                raise LocalGtfsDataError("stop_times.txt references an unknown stop_id")
            sequence = _optional_integer(
                row.get("stop_sequence"),
                field="stop_sequence",
                filename="stop_times.txt",
            )
            if sequence is None or sequence <= last_sequence:
                raise LocalGtfsDataError("Invalid stop_sequence in stop_times.txt")
            last_sequence = sequence
            arrival_seconds = parse_gtfs_time(row.get("arrival_time", ""))
            departure_seconds = parse_gtfs_time(row.get("departure_time", ""))
            pickup_type = _optional_integer(
                row.get("pickup_type"),
                field="pickup_type",
                filename="stop_times.txt",
            )
            drop_off_type = _optional_integer(
                row.get("drop_off_type"),
                field="drop_off_type",
                filename="stop_times.txt",
            )
            pickup_type = 0 if pickup_type is None else pickup_type
            drop_off_type = 0 if drop_off_type is None else drop_off_type
            if not 0 <= pickup_type <= 3 or not 0 <= drop_off_type <= 3:
                raise LocalGtfsDataError("Invalid pickup/drop-off type in stop_times.txt")
            columns = index.get(stop_id)
            if columns is None:
                columns = _StopTimeColumns()
                index[stop_id] = columns
            columns.append(
                trip_index=trip_index,
                event_index=event_count,
                sequence=sequence,
                arrival_seconds=arrival_seconds,
                departure_seconds=departure_seconds,
                pickup_type=pickup_type,
                drop_off_type=drop_off_type,
            )
            trip_events.stop_indexes.append(self._stop_index_by_id[stop_id])
            trip_events.sequences.append(sequence)
            trip_events.arrival_seconds.append(arrival_seconds)
            trip_events.departure_seconds.append(departure_seconds)
            trip_events.pickup_types.append(pickup_type)
            trip_events.drop_off_types.append(drop_off_type)
            event_count += 1
        for offset_index in range(current_trip_index + 1, len(self._trips_by_index) + 1):
            trip_events.trip_offsets[offset_index] = event_count
        for columns in index.values():
            columns.sort_by_departure()
        self._trip_time_index = trip_events
        return index

    def _boardable_stop(self, stop_id: str) -> _Stop:
        stop = self._stops.get(stop_id)
        if stop is None:
            raise ValueError(f"Unknown GTFS stop_id: {stop_id}")
        if stop.location_type != 0:
            raise UnsupportedStopLocation(
                "Select a platform stop (location_type=0); the prototype does not model station walking"
            )
        return stop

    def _load_routes(self) -> dict[str, str | None]:
        routes: dict[str, str | None] = {}
        for row in _read_rows(self._directory, "routes.txt", ("route_id",)):
            route_id = row.get("route_id", "")
            if not route_id or route_id in routes:
                raise LocalGtfsDataError("Blank or duplicate route_id in routes.txt")
            routes[route_id] = _optional_text(row.get("route_short_name"))
        return routes

    def _load_stops(self) -> dict[str, _Stop]:
        stops: dict[str, _Stop] = {}
        for row in _read_rows(
            self._directory,
            "stops.txt",
            ("stop_id", "stop_name"),
        ):
            stop_id = row.get("stop_id", "")
            if not stop_id or stop_id in stops:
                raise LocalGtfsDataError("Blank or duplicate stop_id in stops.txt")
            location_type = _optional_integer(
                row.get("location_type"),
                field="location_type",
                filename="stops.txt",
            )
            stop_access = _optional_integer(
                row.get("stop_access"),
                field="stop_access",
                filename="stops.txt",
            )
            if stop_access not in (None, 0, 1):
                raise LocalGtfsDataError("Invalid stop_access in stops.txt")
            stops[stop_id] = _Stop(
                stop_id=stop_id,
                name=row.get("stop_name", ""),
                location_type=0 if location_type is None else location_type,
                parent_station=_optional_text(row.get("parent_station")),
                stop_access=stop_access,
            )
        return stops

    def _load_transfers(
        self,
    ) -> dict[tuple[str, str], tuple[_TransferRule, ...]]:
        path = self._directory / "transfers.txt"
        if not path.exists():
            return {}

        rules_by_pair: dict[tuple[str, str], list[_TransferRule]] = defaultdict(list)
        source_keys: set[tuple[str, str, str, str, str, str]] = set()
        for row in _read_rows(
            self._directory,
            "transfers.txt",
            ("from_stop_id", "to_stop_id", "transfer_type"),
        ):
            from_stop_id = row.get("from_stop_id", "")
            to_stop_id = row.get("to_stop_id", "")
            if from_stop_id not in self._stops or to_stop_id not in self._stops:
                raise LocalGtfsDataError("transfers.txt references an unknown stop_id")
            transfer_type = _optional_integer(
                row.get("transfer_type"),
                field="transfer_type",
                filename="transfers.txt",
            )
            transfer_type = 0 if transfer_type is None else transfer_type
            if transfer_type not in range(6):
                raise LocalGtfsDataError("Unsupported transfer_type in transfers.txt")
            min_transfer_time = _optional_integer(
                row.get("min_transfer_time"),
                field="min_transfer_time",
                filename="transfers.txt",
            )
            if min_transfer_time is not None and min_transfer_time < 0:
                raise LocalGtfsDataError("Negative min_transfer_time in transfers.txt")
            if transfer_type == 2 and min_transfer_time is None:
                raise LocalGtfsDataError(
                    "transfer_type=2 requires min_transfer_time in transfers.txt"
                )

            from_route_id = _optional_text(row.get("from_route_id"))
            to_route_id = _optional_text(row.get("to_route_id"))
            from_trip_id = _optional_text(row.get("from_trip_id"))
            to_trip_id = _optional_text(row.get("to_trip_id"))
            for route_id in (from_route_id, to_route_id):
                if route_id is not None and route_id not in self._routes:
                    raise LocalGtfsDataError("transfers.txt references an unknown route_id")
            for trip_id, route_id in (
                (from_trip_id, from_route_id),
                (to_trip_id, to_route_id),
            ):
                if trip_id is not None and trip_id not in self._trips:
                    raise LocalGtfsDataError("transfers.txt references an unknown trip_id")
                if (
                    trip_id is not None
                    and route_id is not None
                    and self._trips[trip_id].route_id != route_id
                ):
                    raise LocalGtfsDataError(
                        "transfers.txt trip selector conflicts with its route selector"
                    )
            if transfer_type in (4, 5) and not (from_trip_id and to_trip_id):
                raise LocalGtfsDataError(
                    "transfer_type 4/5 requires both trip selectors"
                )

            source_key = (
                from_stop_id,
                to_stop_id,
                from_trip_id or "",
                to_trip_id or "",
                from_route_id or "",
                to_route_id or "",
            )
            if source_key in source_keys:
                raise LocalGtfsDataError("Duplicate transfer rule primary key")
            source_keys.add(source_key)

            rule = _TransferRule(
                from_stop_id=from_stop_id,
                to_stop_id=to_stop_id,
                transfer_type=transfer_type,
                min_transfer_time_seconds=min_transfer_time,
                from_route_id=from_route_id,
                to_route_id=to_route_id,
                from_trip_id=from_trip_id,
                to_trip_id=to_trip_id,
                specificity=_transfer_specificity(
                    from_trip_id,
                    to_trip_id,
                    from_route_id,
                    to_route_id,
                ),
            )
            for from_platform in self._transfer_stop_platforms(from_stop_id):
                for to_platform in self._transfer_stop_platforms(to_stop_id):
                    rules_by_pair[(from_platform, to_platform)].append(rule)

        return {
            key: tuple(sorted(rules, key=lambda rule: rule.specificity))
            for key, rules in rules_by_pair.items()
        }

    def _transfer_stop_platforms(self, stop_id: str) -> tuple[str, ...]:
        stop = self._stops[stop_id]
        if stop.location_type == 0:
            return (stop_id,)
        if stop.location_type != 1:
            raise LocalGtfsDataError(
                "transfers.txt endpoints must be platforms or parent stations"
            )
        platforms = tuple(self._station_platforms_by_id.get(stop_id, ()))
        if not platforms:
            raise LocalGtfsDataError("Transfer station has no platform children")
        return platforms

    def _load_pathways(self) -> dict[str, tuple[_PathwayEdge, ...]]:
        if not (self._directory / "pathways.txt").exists():
            return {}

        adjacency: dict[str, list[_PathwayEdge]] = defaultdict(list)
        pathway_ids: set[str] = set()
        for row in _read_rows(
            self._directory,
            "pathways.txt",
            (
                "pathway_id",
                "from_stop_id",
                "to_stop_id",
                "pathway_mode",
                "is_bidirectional",
            ),
        ):
            pathway_id = row.get("pathway_id", "")
            from_stop_id = row.get("from_stop_id", "")
            to_stop_id = row.get("to_stop_id", "")
            if not pathway_id or pathway_id in pathway_ids:
                raise LocalGtfsDataError("Blank or duplicate pathway_id in pathways.txt")
            pathway_ids.add(pathway_id)
            if from_stop_id not in self._stops or to_stop_id not in self._stops:
                raise LocalGtfsDataError("pathways.txt references an unknown stop_id")

            pathway_mode = _optional_integer(
                row.get("pathway_mode"),
                field="pathway_mode",
                filename="pathways.txt",
            )
            bidirectional = _optional_integer(
                row.get("is_bidirectional"),
                field="is_bidirectional",
                filename="pathways.txt",
            )
            if pathway_mode not in range(1, 8) or bidirectional not in (0, 1):
                raise LocalGtfsDataError("Invalid mode/direction in pathways.txt")
            if pathway_mode == 7 and bidirectional == 1:
                raise LocalGtfsDataError("Exit-gate pathway cannot be bidirectional")
            for stop_id in (from_stop_id, to_stop_id):
                stop = self._stops[stop_id]
                if stop.location_type not in (0, 2, 3, 4):
                    raise LocalGtfsDataError(
                        "pathways.txt endpoint has an unsupported location_type"
                    )
                if stop.stop_access == 1:
                    raise LocalGtfsDataError(
                        "pathways.txt endpoint is marked stop_access=1"
                    )

            traversal_seconds = _optional_integer(
                row.get("traversal_time"),
                field="traversal_time",
                filename="pathways.txt",
            )
            if traversal_seconds is None:
                continue
            if traversal_seconds <= 0:
                raise LocalGtfsDataError("traversal_time must be positive")
            adjacency[from_stop_id].append(
                _PathwayEdge(
                    to_stop_id=to_stop_id,
                    pathway_id=pathway_id,
                    pathway_mode=pathway_mode,
                    traversal_seconds=traversal_seconds,
                )
            )
            if bidirectional == 1:
                adjacency[to_stop_id].append(
                    _PathwayEdge(
                        to_stop_id=from_stop_id,
                        pathway_id=pathway_id,
                        pathway_mode=pathway_mode,
                        traversal_seconds=traversal_seconds,
                    )
                )

        return {
            stop_id: tuple(
                sorted(edges, key=lambda edge: (edge.to_stop_id, edge.pathway_id))
            )
            for stop_id, edges in adjacency.items()
        }

    def _pathway_paths_from(self, from_stop_id: str) -> dict[str, _PathwayPath]:
        cached = self._pathway_transfer_cache.get(from_stop_id)
        if cached is not None:
            return cached

        shortest_seconds = {from_stop_id: 0}
        previous: dict[str, tuple[str, _PathwayEdge]] = {}
        queue = [(0, from_stop_id)]
        while queue:
            total_seconds, stop_id = heappop(queue)
            if total_seconds != shortest_seconds.get(stop_id):
                continue
            for edge in self._pathways_by_from.get(stop_id, ()):
                candidate_seconds = total_seconds + edge.traversal_seconds
                known_seconds = shortest_seconds.get(edge.to_stop_id)
                if known_seconds is not None and candidate_seconds >= known_seconds:
                    continue
                shortest_seconds[edge.to_stop_id] = candidate_seconds
                previous[edge.to_stop_id] = (stop_id, edge)
                heappush(queue, (candidate_seconds, edge.to_stop_id))

        paths: dict[str, _PathwayPath] = {}
        for to_stop_id in shortest_seconds:
            stop = self._stops[to_stop_id]
            if (
                to_stop_id == from_stop_id
                or stop.location_type != 0
                or stop.stop_access == 1
            ):
                continue
            path_stops = [to_stop_id]
            path_edges: list[_PathwayEdge] = []
            current_stop_id = to_stop_id
            while current_stop_id != from_stop_id:
                prior = previous.get(current_stop_id)
                if prior is None:
                    path_edges = []
                    break
                current_stop_id, edge = prior
                path_stops.append(current_stop_id)
                path_edges.append(edge)
            if not path_edges:
                continue
            path_stops.reverse()
            path_edges.reverse()
            paths[to_stop_id] = _PathwayPath(
                traversal_seconds=shortest_seconds[to_stop_id],
                stop_ids=tuple(path_stops),
                pathway_ids=tuple(edge.pathway_id for edge in path_edges),
                pathway_modes=tuple(edge.pathway_mode for edge in path_edges),
            )
        self._pathway_transfer_cache[from_stop_id] = paths
        return paths

    def _transfer_options_from(
        self,
        from_stop_id: str,
    ) -> tuple[tuple[str, tuple[_TransferRule, ...], _PathwayPath | None], ...]:
        options = {
            to_stop_id: (rules, None)
            for to_stop_id, rules in self._transfer_rules_by_from.get(from_stop_id, ())
        }
        for to_stop_id, path in self._pathway_paths_from(from_stop_id).items():
            rules, _ = options.get(to_stop_id, ((), None))
            options[to_stop_id] = (rules, path)
        return tuple(
            (to_stop_id, rules, path)
            for to_stop_id, (rules, path) in sorted(options.items())
        )

    def _load_calendar(self) -> dict[str, _CalendarRule]:
        calendar: dict[str, _CalendarRule] = {}
        required = ("service_id", *_WEEKDAY_FIELDS, "start_date", "end_date")
        for row in _read_rows(self._directory, "calendar.txt", required):
            service_id = row.get("service_id", "")
            if not service_id or service_id in calendar:
                raise LocalGtfsDataError("Blank or duplicate service_id in calendar.txt")
            weekdays = []
            for field in _WEEKDAY_FIELDS:
                value = row.get(field, "")
                if value not in ("0", "1"):
                    raise LocalGtfsDataError(f"Invalid {field} flag in calendar.txt")
                weekdays.append(value == "1")
            start_date = _parse_gtfs_date(row.get("start_date", ""), filename="calendar.txt")
            end_date = _parse_gtfs_date(row.get("end_date", ""), filename="calendar.txt")
            if start_date > end_date:
                raise LocalGtfsDataError("Invalid date range in calendar.txt")
            calendar[service_id] = _CalendarRule(
                start_date=start_date,
                end_date=end_date,
                weekdays=tuple(weekdays),
            )
        if not calendar:
            raise LocalGtfsDataError("calendar.txt has no service rows")
        return calendar

    def _load_calendar_exceptions(self) -> dict[tuple[str, date], int]:
        exceptions: dict[tuple[str, date], int] = {}
        for row in _read_rows(
            self._directory,
            "calendar_dates.txt",
            ("service_id", "date", "exception_type"),
        ):
            service_id = row.get("service_id", "")
            exception_date = _parse_gtfs_date(
                row.get("date", ""),
                filename="calendar_dates.txt",
            )
            exception_type = _optional_integer(
                row.get("exception_type"),
                field="exception_type",
                filename="calendar_dates.txt",
            )
            if not service_id or exception_type not in (1, 2):
                raise LocalGtfsDataError("Invalid calendar exception in calendar_dates.txt")
            key = (service_id, exception_date)
            if key in exceptions:
                raise LocalGtfsDataError("Duplicate service/date in calendar_dates.txt")
            exceptions[key] = exception_type
        return exceptions

    def _load_trips(self) -> dict[str, _Trip]:
        trips: dict[str, _Trip] = {}
        for row in _read_rows(
            self._directory,
            "trips.txt",
            ("route_id", "service_id", "trip_id"),
        ):
            trip_id = row.get("trip_id", "")
            route_id = row.get("route_id", "")
            service_id = row.get("service_id", "")
            if not trip_id or trip_id in trips or not route_id or not service_id:
                raise LocalGtfsDataError("Blank or duplicate trip identity in trips.txt")
            if route_id not in self._routes:
                raise LocalGtfsDataError("Trip references an unknown route_id")
            direction_id = _optional_integer(
                row.get("direction_id"),
                field="direction_id",
                filename="trips.txt",
            )
            if direction_id not in (None, 0, 1):
                raise LocalGtfsDataError("Invalid direction_id in trips.txt")
            trips[trip_id] = _Trip(
                trip_id=trip_id,
                route_id=route_id,
                service_id=service_id,
                headsign=_optional_text(row.get("trip_headsign")),
                direction_id=direction_id,
            )
        return trips

    def _validate_trip_services(self) -> None:
        calendar_service_ids = set(self._calendar)
        calendar_service_ids.update(service_id for service_id, _ in self._exceptions)
        if any(trip.service_id not in calendar_service_ids for trip in self._trips.values()):
            raise LocalGtfsDataError("Trip references an unknown service_id")

    def _active_service_ids(self, service_date: date) -> set[str]:
        weekday_index = service_date.weekday()
        active = {
            service_id
            for service_id, rule in self._calendar.items()
            if rule.start_date <= service_date <= rule.end_date
            and rule.weekdays[weekday_index]
        }
        for (service_id, exception_date), exception_type in self._exceptions.items():
            if exception_date != service_date:
                continue
            if exception_type == 1:
                active.add(service_id)
            else:
                active.discard(service_id)
        return active
