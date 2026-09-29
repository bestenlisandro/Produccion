export function Loading({ label = 'Cargando…' }: { label?: string }) { return <div className="state" role="status">{label}</div> }
export function ErrorState({ retry }: { retry: () => void }) { return <div className="state" role="alert"><p>No pudimos cargar la información.</p><button onClick={retry}>REINTENTAR</button></div> }
