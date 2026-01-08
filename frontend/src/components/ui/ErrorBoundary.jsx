import React from 'react';

export class ErrorBoundary extends React.Component {
    constructor(props) {
        super(props);
        this.state = { hasError: false, error: null, errorInfo: null };
    }

    static getDerivedStateFromError(error) {
        return { hasError: true, error };
    }

    componentDidCatch(error, errorInfo) {
        console.error("ErrorBoundary caught error:", error, errorInfo);
        this.setState({ errorInfo });
    }

    handleRetry = () => {
        this.setState({ hasError: false, error: null, errorInfo: null });
        // Optional: Trigger a router reload or prop callback?
        // For now, just resetting state re-renders children. 
        // If the error was transient or in useEffect, this might fix it.
        if (this.props.onRetry) {
            this.props.onRetry();
        } else {
            window.location.reload();
        }
    };

    render() {
        if (this.state.hasError) {
            return (
                <div style={{ padding: '2rem', textAlign: 'center', background: '#fff1f2', borderRadius: '12px', margin: '1rem', border: '1px solid #fecdd3' }}>
                    <h3 style={{ color: '#9f1239', marginTop: 0 }}>Algo salió mal 😕</h3>
                    <p style={{ color: '#881337', fontSize: '0.9rem' }}>
                        {this.state.error?.message || "Error desconocido en la interfaz."}
                    </p>
                    <details style={{ textAlign: 'left', marginTop: '1rem', fontSize: '0.75rem', color: '#9f1239', background: '#fff', padding: '0.5rem', borderRadius: '4px' }}>
                        <summary>Detalles técnicos</summary>
                        <pre style={{ overflow: 'auto' }}>
                            {this.state.error?.stack}
                            {this.state.errorInfo?.componentStack}
                        </pre>
                    </details>
                    <button
                        onClick={this.handleRetry}
                        style={{
                            marginTop: '1.5rem',
                            padding: '0.8rem 1.5rem',
                            background: '#e11d48',
                            color: 'white',
                            border: 'none',
                            borderRadius: '8px',
                            fontWeight: 'bold',
                            cursor: 'pointer'
                        }}
                    >
                        Recargar Página
                    </button>
                </div>
            );
        }

        return this.props.children;
    }
}
