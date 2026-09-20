"""Text out of documents: PDF, Office files, HTML (stage 9 item 1).

Pure converters, stdlib plus optional libraries guarded by name. They
lived in `simorgh/execution/` until the product domains moved out of it
and two of them (`knowledge`, `pim`) still needed the same converters
`read_file` and `web_fetch` use. A domain must not import the
Guardian-protected package, so the converters live here, where everyone
may import from and nothing is imported in return -- the same reason
`contracts/home/client.py` is here.
"""
