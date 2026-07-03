# Widget path contract

`Vite(...)` receives the frontend root containing `widgets/`. Python decorator paths are relative to that directory:

```python
@ship.widget(path=Path("hello/widget.tsx"), name="hello")
```

Valid entry names are `widget.tsx` and `widget.jsx`; nested directories are allowed. Do not prefix paths with
`widgets/`, pass an absolute path, or point `Vite(...)` at the `widgets/` directory itself.

The widget key is the relative parent path (`hello` above). Production stores its complete page at
`widgets.hello.html` in `gdansk-manifest.json`.
