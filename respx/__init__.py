"""Offline respx-compatible HTTPX transport interceptor for deterministic sandboxed tests."""

from __future__ import annotations

import functools
import inspect
import re
from collections.abc import AsyncIterator, Callable, Iterable, Iterator
from dataclasses import dataclass
from types import TracebackType
from typing import Any, ParamSpec, TypeVar, cast, overload

import httpx

P = ParamSpec("P")
R = TypeVar("R")

SideEffectItem = httpx.Response | BaseException | type[BaseException]
SideEffectCallable = Callable[..., Any]
SideEffectType = (
    BaseException
    | type[BaseException]
    | SideEffectCallable
    | Iterable[SideEffectItem]
    | None
)


@dataclass(frozen=True)
class Call:
    """Recorded HTTPX request/response pair captured by a mocked Route."""

    request: httpx.Request
    response: httpx.Response | None = None


class CallList(list[Call]):
    """List of recorded HTTPX calls with respx-compatible convenience properties."""

    @property
    def last(self) -> Call:
        if not self:
            raise IndexError("No HTTP calls have been recorded on this route.")
        return self[-1]

    @property
    def call_count(self) -> int:
        return len(self)

    @property
    def called(self) -> bool:
        return bool(self)


def _clone_response(template: httpx.Response, request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        status_code=template.status_code,
        headers=template.headers,
        content=template.content,
        extensions=dict(template.extensions),
        request=request,
    )


class Route:
    """Represents an intercepted HTTPX request matcher and its configured mock behavior."""

    def __init__(
        self,
        *,
        method: str | None = None,
        url: str | re.Pattern[str] | None = None,
        path: str | None = None,
        path__regex: str | re.Pattern[str] | None = None,
        url__regex: str | re.Pattern[str] | None = None,
        host: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> None:
        self._method = method.upper() if method else None
        self._url = url
        self._path = path
        self._path_regex = (
            re.compile(path__regex) if isinstance(path__regex, str) else path__regex
        )
        self._url_regex = re.compile(url__regex) if isinstance(url__regex, str) else url__regex
        self._host = host
        self._params = params
        self._return_value: httpx.Response | None = None
        self._side_effect: SideEffectType = None
        self._side_effect_iter: Iterator[SideEffectItem] | None = None
        self.calls: CallList = CallList()

    @property
    def called(self) -> bool:
        return bool(self.calls)

    @property
    def call_count(self) -> int:
        return len(self.calls)

    @property
    def return_value(self) -> httpx.Response | None:
        return self._return_value

    @return_value.setter
    def return_value(self, value: httpx.Response | None) -> None:
        self._return_value = value

    @property
    def side_effect(self) -> SideEffectType:
        return self._side_effect

    @side_effect.setter
    def side_effect(self, value: SideEffectType) -> None:
        self._side_effect = value
        if (
            value is not None
            and not isinstance(value, (BaseException, type))
            and not callable(value)
            and isinstance(value, Iterable)
        ):
            self._side_effect_iter = iter(value)
        else:
            self._side_effect_iter = None

    def mock(
        self,
        return_value: httpx.Response | None = None,
        *,
        side_effect: SideEffectType = None,
    ) -> Route:
        """Configure the canned response or side effect for matching requests."""
        self.return_value = return_value
        self.side_effect = side_effect
        return self

    def respond(
        self,
        status_code: int = 200,
        *,
        headers: dict[str, str] | None = None,
        content: bytes | str | None = None,
        text: str | None = None,
        json: Any = None,
    ) -> Route:
        """Shorthand helper matching respx Route.respond(...)."""
        kwargs: dict[str, Any] = {"status_code": status_code}
        if headers is not None:
            kwargs["headers"] = headers
        if json is not None:
            kwargs["json"] = json
        elif text is not None:
            kwargs["text"] = text
        elif content is not None:
            kwargs["content"] = content
        self.return_value = httpx.Response(**kwargs)
        self.side_effect = None
        return self

    def matches(self, request: httpx.Request) -> bool:
        if self._method is not None and request.method.upper() != self._method:
            return False

        req_url_str = str(request.url)
        req_path = request.url.path

        if self._host is not None and request.url.host != self._host:
            return False

        if self._url is not None:
            if isinstance(self._url, re.Pattern):
                if not self._url.search(req_url_str):
                    return False
            elif self._url.startswith("/"):
                if not _path_matches(req_path, self._url):
                    return False
            elif "?" in self._url:
                if req_url_str != self._url:
                    return False
            else:
                base_req_url = req_url_str.split("?", 1)[0]
                if base_req_url.rstrip("/") != self._url.rstrip("/"):
                    return False

        if self._path is not None and not _path_matches(req_path, self._path):
            return False

        if self._path_regex is not None and not self._path_regex.search(req_path):
            return False

        if self._url_regex is not None and not self._url_regex.search(req_url_str):
            return False

        if self._params is not None:
            for key, expected in self._params.items():
                if request.url.params.get(key) != str(expected):
                    return False

        return True

    def _raise_or_unwrap(
        self, item: Any, request: httpx.Request
    ) -> httpx.Response:
        if isinstance(item, BaseException):
            self.calls.append(Call(request=request, response=None))
            raise item
        if isinstance(item, type) and issubclass(item, BaseException):
            self.calls.append(Call(request=request, response=None))
            if issubclass(item, httpx.RequestError):
                raise item(f"Mocked {item.__name__}", request=request)
            raise item(f"Mocked {item.__name__}")
        if isinstance(item, httpx.Response):
            cloned = _clone_response(item, request)
            self.calls.append(Call(request=request, response=cloned))
            return cloned
        raise TypeError(f"Unsupported respx mock result: {item!r}")

    async def handle_async(self, request: httpx.Request) -> httpx.Response:
        if self._side_effect_iter is not None:
            item = next(self._side_effect_iter)
            return self._raise_or_unwrap(item, request)

        if self._side_effect is not None:
            if isinstance(self._side_effect, BaseException) or (
                isinstance(self._side_effect, type)
                and issubclass(self._side_effect, BaseException)
            ):
                return self._raise_or_unwrap(self._side_effect, request)
            if callable(self._side_effect):
                fn = cast("SideEffectCallable", self._side_effect)
                sig = inspect.signature(fn)
                result = fn(request, self) if len(sig.parameters) >= 2 else fn(request)
                if inspect.isawaitable(result):
                    result = await result
                return self._raise_or_unwrap(result, request)

        if self._return_value is not None:
            return self._raise_or_unwrap(self._return_value, request)

        default_resp = httpx.Response(200, request=request)
        self.calls.append(Call(request=request, response=default_resp))
        return default_resp

    def handle_sync(self, request: httpx.Request) -> httpx.Response:
        if self._side_effect_iter is not None:
            item = next(self._side_effect_iter)
            return self._raise_or_unwrap(item, request)

        if self._side_effect is not None:
            if isinstance(self._side_effect, BaseException) or (
                isinstance(self._side_effect, type)
                and issubclass(self._side_effect, BaseException)
            ):
                return self._raise_or_unwrap(self._side_effect, request)
            if callable(self._side_effect):
                fn = cast("SideEffectCallable", self._side_effect)
                sig = inspect.signature(fn)
                result = fn(request, self) if len(sig.parameters) >= 2 else fn(request)
                return self._raise_or_unwrap(result, request)

        if self._return_value is not None:
            return self._raise_or_unwrap(self._return_value, request)

        default_resp = httpx.Response(200, request=request)
        self.calls.append(Call(request=request, response=default_resp))
        return default_resp


def _path_matches(actual_path: str, expected_path: str) -> bool:
    norm_actual = actual_path.rstrip("/") or "/"
    norm_expected = expected_path.rstrip("/") or "/"
    if norm_actual == norm_expected:
        return True
    # Support matching relative endpoint paths (e.g. "/incidents/INC-1") when AsyncClient
    # has a versioned base_url like "https://api.test.internal/v1".
    if norm_expected.startswith("/") and norm_actual.endswith(norm_expected):
        prefix = norm_actual[: -len(norm_expected)]
        if not prefix or not prefix.endswith("/"):
            return True
    return False


_ORIG_ASYNC_HANDLE = httpx.AsyncHTTPTransport.handle_async_request
_ORIG_SYNC_HANDLE = httpx.HTTPTransport.handle_request
_ACTIVE_ROUTERS: list[MockRouter] = []


async def _patched_handle_async_request(
    _self: httpx.AsyncHTTPTransport,
    request: httpx.Request,
) -> httpx.Response:
    if not _ACTIVE_ROUTERS:
        raise httpx.ConnectError(
            f"Outbound HTTP blocked cleanly by respx outside active router: {request.url}",
            request=request,
        )
    return await _ACTIVE_ROUTERS[-1].dispatch_async(request)


def _patched_handle_sync_request(
    _self: httpx.HTTPTransport,
    request: httpx.Request,
) -> httpx.Response:
    if not _ACTIVE_ROUTERS:
        raise httpx.ConnectError(
            f"Outbound HTTP blocked cleanly by respx outside active router: {request.url}",
            request=request,
        )
    return _ACTIVE_ROUTERS[-1].dispatch_sync(request)


def _install_transport_patches() -> None:
    httpx.AsyncHTTPTransport.handle_async_request = _patched_handle_async_request  # type: ignore[method-assign,assignment]
    httpx.HTTPTransport.handle_request = _patched_handle_sync_request  # type: ignore[method-assign,assignment]


def _restore_transport_patches() -> None:
    if not _ACTIVE_ROUTERS:
        httpx.AsyncHTTPTransport.handle_async_request = _ORIG_ASYNC_HANDLE  # type: ignore[method-assign]
        httpx.HTTPTransport.handle_request = _ORIG_SYNC_HANDLE  # type: ignore[method-assign]


class MockRouter:
    """Context manager and function decorator routing HTTPX traffic to in-memory Route mocks."""

    def __init__(
        self,
        *,
        assert_all_called: bool = False,
        assert_all_mocked: bool = True,
        base_url: str | None = None,
    ) -> None:
        self._assert_all_called = assert_all_called
        self._assert_all_mocked = assert_all_mocked
        self._base_url = base_url.rstrip("/") if base_url else None
        self._routes: list[Route] = []
        self.calls: CallList = CallList()

    def reset(self) -> None:
        self._routes.clear()
        self.calls.clear()

    def start(self) -> MockRouter:
        self.reset()
        if not _ACTIVE_ROUTERS:
            _install_transport_patches()
        _ACTIVE_ROUTERS.append(self)
        return self

    def stop(self, exc_type: type[BaseException] | None = None) -> None:
        try:
            if self in _ACTIVE_ROUTERS:
                _ACTIVE_ROUTERS.remove(self)
            if exc_type is None and self._assert_all_called:
                uncalled = [r for r in self._routes if not r.called]
                if uncalled:
                    raise AssertionError(
                        f"Expected all respx routes to be called; {len(uncalled)} uncalled."
                    )
        finally:
            self.reset()
            _restore_transport_patches()

    def __enter__(self) -> MockRouter:
        return self.start()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.stop(exc_type)

    async def __aenter__(self) -> MockRouter:
        return self.start()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.stop(exc_type)

    @overload
    def __call__(self, func: Callable[P, R]) -> Callable[P, R]: ...

    @overload
    def __call__(
        self,
        func: None = None,
        *,
        assert_all_called: bool = False,
        assert_all_mocked: bool = True,
        base_url: str | None = None,
    ) -> MockRouter: ...

    def __call__(
        self,
        func: Callable[P, R] | None = None,
        *,
        assert_all_called: bool = False,
        assert_all_mocked: bool = True,
        base_url: str | None = None,
    ) -> Callable[P, R] | MockRouter:
        if func is None:
            return MockRouter(
                assert_all_called=assert_all_called,
                assert_all_mocked=assert_all_mocked,
                base_url=base_url,
            )

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def _async_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
                router = MockRouter(
                    assert_all_called=self._assert_all_called,
                    assert_all_mocked=self._assert_all_mocked,
                    base_url=self._base_url,
                )
                async with router:
                    return await func(*args, **kwargs)

            return _async_wrapper  # type: ignore[return-value]

        @functools.wraps(func)
        def _sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            router = MockRouter(
                assert_all_called=self._assert_all_called,
                assert_all_mocked=self._assert_all_mocked,
                base_url=self._base_url,
            )
            with router:
                return func(*args, **kwargs)

        return _sync_wrapper

    def _resolve_url(self, url: str | re.Pattern[str] | None) -> str | re.Pattern[str] | None:
        if isinstance(url, str) and self._base_url and url.startswith("/"):
            return f"{self._base_url}{url}"
        return url

    def route(
        self,
        *,
        method: str | None = None,
        url: str | re.Pattern[str] | None = None,
        path: str | None = None,
        path__regex: str | re.Pattern[str] | None = None,
        url__regex: str | re.Pattern[str] | None = None,
        host: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> Route:
        new_route = Route(
            method=method,
            url=self._resolve_url(url),
            path=path,
            path__regex=path__regex,
            url__regex=url__regex,
            host=host,
            params=params,
        )
        self._routes.append(new_route)
        return new_route

    def get(
        self,
        url: str | re.Pattern[str] | None = None,
        *,
        path: str | None = None,
        path__regex: str | re.Pattern[str] | None = None,
        url__regex: str | re.Pattern[str] | None = None,
        host: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> Route:
        return self.route(
            method="GET",
            url=url,
            path=path,
            path__regex=path__regex,
            url__regex=url__regex,
            host=host,
            params=params,
        )

    def post(
        self,
        url: str | re.Pattern[str] | None = None,
        *,
        path: str | None = None,
        path__regex: str | re.Pattern[str] | None = None,
        url__regex: str | re.Pattern[str] | None = None,
        host: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> Route:
        return self.route(
            method="POST",
            url=url,
            path=path,
            path__regex=path__regex,
            url__regex=url__regex,
            host=host,
            params=params,
        )

    def put(
        self,
        url: str | re.Pattern[str] | None = None,
        *,
        path: str | None = None,
        path__regex: str | re.Pattern[str] | None = None,
        url__regex: str | re.Pattern[str] | None = None,
        host: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> Route:
        return self.route(
            method="PUT",
            url=url,
            path=path,
            path__regex=path__regex,
            url__regex=url__regex,
            host=host,
            params=params,
        )

    def patch(
        self,
        url: str | re.Pattern[str] | None = None,
        *,
        path: str | None = None,
        path__regex: str | re.Pattern[str] | None = None,
        url__regex: str | re.Pattern[str] | None = None,
        host: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> Route:
        return self.route(
            method="PATCH",
            url=url,
            path=path,
            path__regex=path__regex,
            url__regex=url__regex,
            host=host,
            params=params,
        )

    def delete(
        self,
        url: str | re.Pattern[str] | None = None,
        *,
        path: str | None = None,
        path__regex: str | re.Pattern[str] | None = None,
        url__regex: str | re.Pattern[str] | None = None,
        host: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> Route:
        return self.route(
            method="DELETE",
            url=url,
            path=path,
            path__regex=path__regex,
            url__regex=url__regex,
            host=host,
            params=params,
        )

    def head(
        self,
        url: str | re.Pattern[str] | None = None,
        *,
        path: str | None = None,
        path__regex: str | re.Pattern[str] | None = None,
        url__regex: str | re.Pattern[str] | None = None,
        host: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> Route:
        return self.route(
            method="HEAD",
            url=url,
            path=path,
            path__regex=path__regex,
            url__regex=url__regex,
            host=host,
            params=params,
        )

    def options(
        self,
        url: str | re.Pattern[str] | None = None,
        *,
        path: str | None = None,
        path__regex: str | re.Pattern[str] | None = None,
        url__regex: str | re.Pattern[str] | None = None,
        host: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> Route:
        return self.route(
            method="OPTIONS",
            url=url,
            path=path,
            path__regex=path__regex,
            url__regex=url__regex,
            host=host,
            params=params,
        )

    def _find_matching_route(self, request: httpx.Request) -> Route:
        # LIFO matching so re-registered mocks mid-test override earlier catch-all routes
        for candidate in reversed(self._routes):
            if candidate.matches(request):
                return candidate
        if self._assert_all_mocked:
            raise httpx.ConnectError(
                f"RESPX: Unmocked HTTP {request.method} request to {request.url}",
                request=request,
            )
        return Route()

    async def dispatch_async(self, request: httpx.Request) -> httpx.Response:
        matched = self._find_matching_route(request)
        try:
            response = await matched.handle_async(request)
        except BaseException:
            self.calls.append(Call(request=request, response=None))
            raise
        self.calls.append(Call(request=request, response=response))
        return response

    def dispatch_sync(self, request: httpx.Request) -> httpx.Response:
        matched = self._find_matching_route(request)
        try:
            response = matched.handle_sync(request)
        except BaseException:
            self.calls.append(Call(request=request, response=None))
            raise
        self.calls.append(Call(request=request, response=response))
        return response


mock = MockRouter()


def _current_router() -> MockRouter:
    return _ACTIVE_ROUTERS[-1] if _ACTIVE_ROUTERS else mock


def route(
    method: str | None = None,
    url: str | re.Pattern[str] | None = None,
    *,
    path: str | None = None,
    path__regex: str | re.Pattern[str] | None = None,
    url__regex: str | re.Pattern[str] | None = None,
    host: str | None = None,
    params: dict[str, Any] | None = None,
) -> Route:
    return _current_router().route(
        method=method,
        url=url,
        path=path,
        path__regex=path__regex,
        url__regex=url__regex,
        host=host,
        params=params,
    )


def get(
    url: str | re.Pattern[str] | None = None,
    *,
    path: str | None = None,
    path__regex: str | re.Pattern[str] | None = None,
    url__regex: str | re.Pattern[str] | None = None,
    host: str | None = None,
    params: dict[str, Any] | None = None,
) -> Route:
    return _current_router().get(
        url=url,
        path=path,
        path__regex=path__regex,
        url__regex=url__regex,
        host=host,
        params=params,
    )


def post(
    url: str | re.Pattern[str] | None = None,
    *,
    path: str | None = None,
    path__regex: str | re.Pattern[str] | None = None,
    url__regex: str | re.Pattern[str] | None = None,
    host: str | None = None,
    params: dict[str, Any] | None = None,
) -> Route:
    return _current_router().post(
        url=url,
        path=path,
        path__regex=path__regex,
        url__regex=url__regex,
        host=host,
        params=params,
    )


def put(
    url: str | re.Pattern[str] | None = None,
    *,
    path: str | None = None,
    path__regex: str | re.Pattern[str] | None = None,
    url__regex: str | re.Pattern[str] | None = None,
    host: str | None = None,
    params: dict[str, Any] | None = None,
) -> Route:
    return _current_router().put(
        url=url,
        path=path,
        path__regex=path__regex,
        url__regex=url__regex,
        host=host,
        params=params,
    )


def patch(
    url: str | re.Pattern[str] | None = None,
    *,
    path: str | None = None,
    path__regex: str | re.Pattern[str] | None = None,
    url__regex: str | re.Pattern[str] | None = None,
    host: str | None = None,
    params: dict[str, Any] | None = None,
) -> Route:
    return _current_router().patch(
        url=url,
        path=path,
        path__regex=path__regex,
        url__regex=url__regex,
        host=host,
        params=params,
    )


def delete(
    url: str | re.Pattern[str] | None = None,
    *,
    path: str | None = None,
    path__regex: str | re.Pattern[str] | None = None,
    url__regex: str | re.Pattern[str] | None = None,
    host: str | None = None,
    params: dict[str, Any] | None = None,
) -> Route:
    return _current_router().delete(
        url=url,
        path=path,
        path__regex=path__regex,
        url__regex=url__regex,
        host=host,
        params=params,
    )


def head(
    url: str | re.Pattern[str] | None = None,
    *,
    path: str | None = None,
    path__regex: str | re.Pattern[str] | None = None,
    url__regex: str | re.Pattern[str] | None = None,
    host: str | None = None,
    params: dict[str, Any] | None = None,
) -> Route:
    return _current_router().head(
        url=url,
        path=path,
        path__regex=path__regex,
        url__regex=url__regex,
        host=host,
        params=params,
    )


def options(
    url: str | re.Pattern[str] | None = None,
    *,
    path: str | None = None,
    path__regex: str | re.Pattern[str] | None = None,
    url__regex: str | re.Pattern[str] | None = None,
    host: str | None = None,
    params: dict[str, Any] | None = None,
) -> Route:
    return _current_router().options(
        url=url,
        path=path,
        path__regex=path__regex,
        url__regex=url__regex,
        host=host,
        params=params,
    )


__all__ = [
    "AsyncIterator",
    "Call",
    "CallList",
    "MockRouter",
    "Route",
    "delete",
    "get",
    "head",
    "mock",
    "options",
    "patch",
    "post",
    "put",
    "route",
]
