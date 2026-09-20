"""Query layer P4: wiring pipeline → payload HTTP (spec §2, contract §1).

I payload sono dict costruiti ESPLICITAMENTE (nessun ``exclude_none``): la
semantica ``undefined`` del TS (chiave omessa) e ``null`` (chiave presente con
null) va replicata chiave per chiave — i golden fanno fede.
"""
