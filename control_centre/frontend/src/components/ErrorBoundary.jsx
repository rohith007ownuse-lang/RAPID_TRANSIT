import { Component } from 'react'

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, errorInfo) {
    console.error('ErrorBoundary caught:', error, errorInfo)
  }

  handleReload = () => {
    this.setState({ hasError: false, error: null })
    window.location.reload()
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="error-boundary">
          <div className="error-boundary-card">
            <div style={{ fontSize: 40, marginBottom: 12 }}>⚠️</div>
            <h2 style={{ margin: '0 0 8px', fontSize: 18 }}>Something went wrong</h2>
            <p className="muted" style={{ margin: '0 0 16px', fontSize: 13 }}>
              {this.state.error?.message || 'An unexpected error occurred'}
            </p>
            <button className="btn btn-primary" onClick={this.handleReload}>
              Reload Page
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
